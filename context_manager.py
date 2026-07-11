# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
context_manager.py — contexte conversation dynamique avec résumé roulant.

Objectif : la base de données garde l'intégralité de l'historique (rien n'est jamais
supprimé), mais ce qui est ENVOYÉ au LLM à chaque tour est recalibré pour rester sous un
budget de tokens (estimation prudente, pas de tokenizer réel — pas de nouvelle dépendance).

Pièces :
  - estimate_tokens(text) : estimation grossière mais stable, len(text) / 3.5.
  - effective_input_budget(settings) : budget réel d'entrée, jamais sous 1024 tokens.
  - build_history_budgeted(...) : remplace l'ancien build_history() bugué (ASC + LIMIT, qui
    envoyait les PREMIERS messages d'une longue conversation au lieu des derniers).
  - get_memory_block_budgeted(...) : variante budgétée de get_memory_block(), ne tronque
    jamais une entrée au milieu, retire des entrées entières si besoin.
  - compact_chat_context(...) : consolidation via le LLM utility, résumé roulant stocké
    dans chat_context_summaries (table séparée des mémoires persistantes du personnage).
  - schedule_compaction(...) / cancel : déclenchement différé après 20s d'inactivité,
    jamais de LLM utility synchrone après chaque message.

Rien ici ne touche au routage LLM (llm_chat/llm_util_chat), à l'offload VRAM, à ComfyUI, aux
workflows image, au TTS, aux humeurs ni à la galerie — ce module ne fait que décider QUOI
envoyer au modèle conversation, jamais COMMENT l'appeler.
"""
import logging
import math
import threading
import time

log = logging.getLogger("AmiorAI.context")

# --------------------------------------------------------------------------- #
#  Estimation de tokens (prudente, sans dépendance externe)
# --------------------------------------------------------------------------- #
def estimate_tokens(text):
    """Estimation grossière du nombre de tokens d'un texte. Pas un vrai tokenizer (aucune
    dépendance ajoutée) : sert uniquement à budgéter, pas à une exactitude stricte."""
    if not text:
        return 0
    return math.ceil(len(text) / 3.5)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def get_context_distribution(settings):
    """Source UNIQUE de verite pour la repartition du budget de contexte (v10). Lit
    uniquement llm_ctx et llm_max_tokens (les deux sliders exposes a l'utilisateur) quand
    context_distribution_mode = 'auto' (par defaut). Les anciennes cles
    (context_input_target_tokens, context_memory_max_tokens, context_summary_max_tokens,
    context_recent_messages) restent lues en base pour compatibilite mais ne pilotent plus
    le calcul en mode auto -- seulement si l'utilisateur force context_distribution_mode a
    autre chose que 'auto' (mode legacy, conserve pour ne jamais casser une config existante
    qui en dependrait explicitement).

    Renvoie un dict : context_limit, response_max_tokens, safety_margin, input_budget,
    memory_budget, summary_budget, recent_messages."""
    try:
        context_limit = _clamp(int(settings.get("llm_ctx", 8192)), 2048, 32768)
    except (TypeError, ValueError):
        context_limit = 8192
    try:
        response_max_tokens = _clamp(int(settings.get("llm_max_tokens", 250)), 50, 600)
    except (TypeError, ValueError):
        response_max_tokens = 250

    mode = (settings.get("context_distribution_mode") or "auto").strip().lower()

    if mode != "auto":
        # Mode legacy explicite : reprend l'ancien calcul plafonne par
        # context_input_target_tokens, pour compatibilite avec une config qui en dependrait.
        try:
            target = int(settings.get("context_input_target_tokens", 3500))
        except (TypeError, ValueError):
            target = 3500
        input_budget = max(1024, min(target, context_limit - response_max_tokens - 256))
        try:
            memory_budget = int(settings.get("context_memory_max_tokens", 700))
        except (TypeError, ValueError):
            memory_budget = 700
        try:
            summary_budget = int(settings.get("context_summary_max_tokens", 900))
        except (TypeError, ValueError):
            summary_budget = 900
        try:
            recent_messages = int(settings.get("context_recent_messages", 8))
        except (TypeError, ValueError):
            recent_messages = 8
        return {
            "context_limit": context_limit, "response_max_tokens": response_max_tokens,
            "safety_margin": 256, "input_budget": input_budget,
            "memory_budget": memory_budget, "summary_budget": summary_budget,
            "recent_messages": recent_messages,
        }

    safety_margin = 384
    hard_input_limit = max(768, context_limit - response_max_tokens - safety_margin)
    # AmiorAI utilise au plus 75% du contexte pour l'entree, afin de preserver une marge
    # saine pour la reponse, les variations d'estimation de tokens et le prompt systeme.
    input_budget = min(hard_input_limit, round(context_limit * 0.75))
    input_budget = max(768, input_budget)

    if input_budget >= 4500:
        memory_budget = _clamp(round(input_budget * 0.20), 700, 1400)
        summary_budget = _clamp(round(input_budget * 0.20), 900, 1500)
        recent_messages = _clamp(round(input_budget / 500), 8, 14)
    elif input_budget >= 2500:
        memory_budget = _clamp(round(input_budget * 0.17), 400, 900)
        summary_budget = _clamp(round(input_budget * 0.17), 500, 1000)
        recent_messages = _clamp(round(input_budget / 575), 6, 10)
    else:
        memory_budget = _clamp(round(input_budget * 0.15), 250, 500)
        summary_budget = _clamp(round(input_budget * 0.15), 300, 600)
        recent_messages = _clamp(round(input_budget / 650), 4, 7)

    return {
        "context_limit": context_limit,
        "response_max_tokens": response_max_tokens,
        "safety_margin": safety_margin,
        "input_budget": input_budget,
        "memory_budget": memory_budget,
        "summary_budget": summary_budget,
        "recent_messages": recent_messages,
    }


def effective_input_budget(settings):
    """Budget réel d'entrée pour le contexte envoyé au LLM. Depuis v10, délègue à
    get_context_distribution() (source unique de vérité) : ne descend jamais sous 1024
    tokens, exploite réellement llm_ctx au lieu d'être plafonné artificiellement par
    context_input_target_tokens. Conservée pour compatibilité (plusieurs appelants
    existants), mais get_context_distribution() doit être préférée pour tout nouveau code
    ayant besoin de mémoire/résumé/messages récents en plus du seul budget d'entrée."""
    dist = get_context_distribution(settings)
    return max(1024, dist["input_budget"])


# --------------------------------------------------------------------------- #
#  Schéma DB du résumé roulant — table séparée, non destructive
# --------------------------------------------------------------------------- #
def ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chat_context_summaries (
            chat_id TEXT PRIMARY KEY,
            summary TEXT DEFAULT '',
            summarized_until REAL DEFAULT 0,
            last_summary_at REAL,
            updated_at REAL,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        );
        """
    )


def get_chat_summary(conn, chat_id):
    row = conn.execute(
        "SELECT * FROM chat_context_summaries WHERE chat_id=?", (chat_id,)
    ).fetchone()
    if row:
        return dict(row)
    return {"chat_id": chat_id, "summary": "", "summarized_until": 0,
            "last_summary_at": None, "updated_at": None}


def save_chat_summary(conn, chat_id, summary, summarized_until):
    now = time.time()
    conn.execute(
        "INSERT INTO chat_context_summaries(chat_id, summary, summarized_until, "
        "last_summary_at, updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET summary=excluded.summary, "
        "summarized_until=excluded.summarized_until, last_summary_at=excluded.last_summary_at, "
        "updated_at=excluded.updated_at",
        (chat_id, summary, summarized_until, now, now),
    )


# --------------------------------------------------------------------------- #
#  Construction budgétée de l'historique des messages
# --------------------------------------------------------------------------- #
def build_history_budgeted(db_fn, chat_id, char_for_assistant_id, settings, group=False):
    """Remplace l'ancien build_history() : récupère toujours les messages les PLUS RÉCENTS
    (ORDER BY created_at DESC), jamais les premiers d'une longue conversation, puis les
    remet en ordre chronologique avant l'envoi. N'inclut jamais un message déjà couvert par
    le résumé roulant (created_at <= summarized_until). Réduit le nombre de messages bruts
    selon le budget restant si nécessaire (via reduce_history_to_budget, appelée par
    l'appelant), mais garde toujours le tout dernier message utilisateur. Depuis v10, le
    nombre de messages recents vient de get_context_distribution (calcule depuis llm_ctx +
    llm_max_tokens), pas de l'ancienne cle fixe context_recent_messages."""
    recent_n = max(1, get_context_distribution(settings)["recent_messages"])

    with db_fn() as c:
        summarized_until = get_chat_summary(c, chat_id)["summarized_until"] or 0
        # On prend une marge (recent_n * 3) pour avoir de quoi reduire ensuite si le budget
        # est serre, sans avoir a refaire une requete SQL.
        rows = c.execute(
            "SELECT role, character_id, content, created_at FROM messages "
            "WHERE chat_id=? AND created_at > ? ORDER BY created_at DESC LIMIT ?",
            (chat_id, summarized_until, max(recent_n * 3, 24)),
        ).fetchall()
        names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM characters").fetchall()}

    rows = list(reversed(rows))  # remet en ordre chronologique

    def to_msg(r):
        if r["role"] == "user":
            return {"role": "user", "content": r["content"]}
        if group and r["character_id"] != char_for_assistant_id:
            speaker = names.get(r["character_id"], "?")
            return {"role": "user", "content": f"({speaker}) {r['content']}"}
        return {"role": "assistant", "content": r["content"]}

    all_msgs = [to_msg(r) for r in rows]
    return all_msgs[-recent_n:] if len(all_msgs) > recent_n else all_msgs


def reduce_history_to_budget(history, budget_tokens):
    """Si les derniers messages bruts dépassent le budget qui leur est alloué, retire les
    PLUS ANCIENS d'entre eux un par un (jamais de coupe au milieu d'un message), en gardant
    toujours au moins le tout dernier message (qui est le message utilisateur le plus
    récent dans le flux normal)."""
    if not history:
        return history
    kept = list(history)
    while len(kept) > 1 and sum(estimate_tokens(m["content"]) for m in kept) > budget_tokens:
        kept.pop(0)
    return kept


# --------------------------------------------------------------------------- #
#  Mémoire persistante budgétée (variante de get_memory_block, n'écrit rien)
# --------------------------------------------------------------------------- #
def build_memory_block_budgeted(structured_parts, long_entries, short_parts, budget_tokens):
    """Construit le bloc mémoire en respectant le budget, sans jamais tronquer une entrée
    au milieu. Ordre de priorité : faits structurés (toujours gardés en entier, c'est ce
    qu'il y a de plus important et de plus compact) > mémoires longues non structurées
    (les plus récentes d'abord) > mémoires courtes (les plus récentes d'abord). Retire des
    ENTRÉES ENTIÈRES, jamais une coupe arbitraire en plein milieu de texte."""
    block = ""
    used = 0

    if structured_parts:
        text = "\n\n[Long-term memory]\n" + "\n".join(f"- {p}" for p in structured_parts)
        cost = estimate_tokens(text)
        block += text
        used += cost

    # Mémoires longues non structurées : les plus récentes d'abord (long_entries est déjà
    # trié ASC en entrée -> on les ajoute en partant de la fin tant qu'il reste du budget).
    kept_long = []
    for entry in reversed(long_entries):
        cost = estimate_tokens(entry)
        if used + cost > budget_tokens:
            break
        kept_long.insert(0, entry)
        used += cost
    if kept_long:
        extra = "\n".join(f"- {p}" for p in kept_long)
        if "[Long-term memory]" not in block:
            block += "\n\n[Long-term memory]\n" + extra
        else:
            block += "\n" + extra

    # Memoires courtes : meme logique, les plus recentes d'abord.
    kept_short = []
    for entry in reversed(short_parts):
        cost = estimate_tokens(entry)
        if used + cost > budget_tokens:
            break
        kept_short.insert(0, entry)
        used += cost
    if kept_short:
        block += "\n\n[Short-term memory]\n" + "\n".join(f"- {p}" for p in kept_short)

    return block, used


# --------------------------------------------------------------------------- #
#  Consolidation (résumé roulant) — appelle le LLM UTILITAIRE, jamais le conversation
# --------------------------------------------------------------------------- #
COMPACTION_PROMPT = (
    "Return JSON only.\n\n"
    "Create a compact rolling summary of this conversation.\n\n"
    "Keep only information necessary for continuity:\n"
    "- established facts and preferences;\n"
    "- current emotional and relationship state;\n"
    "- scene, location, actions in progress;\n"
    "- promises, decisions and unresolved subjects;\n"
    "- important character reactions;\n"
    "- facts that must not be contradicted later.\n\n"
    "Do not invent facts.\n"
    "Do not include generic filler.\n"
    "Do not reproduce dialogue.\n"
    "Do not include instructions to the model.\n\n"
    "Return:\n"
    "{\n"
    '  "summary": "compact factual summary",\n'
    '  "last_topic": "short current topic",\n'
    '  "current_relationship_state": "short relationship state"\n'
    "}"
)


def compact_chat_context(db_fn, llm_util_chat_fn, extract_json_fn, save_char_memory_fn,
                         chat_id, character_id, settings, is_group=False):
    """Consolide les anciens messages d'un chat en un resume roulant compact, via le LLM
    UTILITAIRE (jamais le conversation). Best-effort : toute erreur est loggee et
    n'interrompt jamais le chat (si l'utility echoue, on garde tout en base et on
    reessaiera plus tard).

    db_fn : fonction db() de app.py (context manager de connexion).
    llm_util_chat_fn : llm_util_chat de engine.py (injectee pour eviter un import circulaire).
    extract_json_fn : _extract_json de app.py.
    save_char_memory_fn : save_char_memory de app.py (mise a jour last_topic/relation pour
        les chats a 2 personnages uniquement -- jamais pour un groupe)."""
    distribution = get_context_distribution(settings)
    max_summary_tokens = distribution["summary_budget"]

    with db_fn() as c:
        prev = get_chat_summary(c, chat_id)
        names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM characters").fetchall()}
        recent_n = distribution["recent_messages"]
        all_unsummarized = c.execute(
            "SELECT role, character_id, content, created_at FROM messages "
            "WHERE chat_id=? AND created_at > ? ORDER BY created_at ASC",
            (chat_id, prev["summarized_until"] or 0),
        ).fetchall()

    if len(all_unsummarized) <= max(recent_n, 1):
        log.info("[context] Consolidation skipped: not enough old messages to absorb")
        return prev

    to_absorb = all_unsummarized[:-recent_n] if recent_n > 0 else all_unsummarized
    if not to_absorb:
        return prev

    lines = []
    for r in to_absorb:
        if r["role"] == "user":
            lines.append(f"[user] {r['content']}")
        else:
            speaker = names.get(r["character_id"], "?") if is_group else "assistant"
            lines.append(f"[{speaker}] {r['content']}")
    excerpt = "\n".join(lines)

    user_content = ""
    if prev.get("summary"):
        user_content += "PREVIOUS SUMMARY:\n" + prev["summary"] + "\n\n"
    user_content += "NEW MESSAGES TO ABSORB:\n" + excerpt

    try:
        raw = llm_util_chat_fn(
            [{"role": "system", "content": COMPACTION_PROMPT},
             {"role": "user", "content": user_content}],
            settings, max_tokens=max_summary_tokens, temperature=0.3)
        parsed = extract_json_fn(raw)
        new_summary = (parsed.get("summary") or "").strip()
        if not new_summary:
            raise ValueError("Empty summary returned by utility LLM.")
    except Exception as e:  # noqa: BLE001
        log.warning(f"[context] Consolidation failed: chat kept with recent context ({e})")
        return prev

    new_until = to_absorb[-1]["created_at"]
    with db_fn() as c:
        save_chat_summary(c, chat_id, new_summary, new_until)

    if not is_group and character_id:
        update = {}
        if parsed.get("last_topic"):
            update["last_topic"] = parsed["last_topic"]
        if parsed.get("current_relationship_state"):
            update["current_relationship_state"] = parsed["current_relationship_state"]
        if update:
            try:
                save_char_memory_fn(character_id, **update)
            except Exception as e:  # noqa: BLE001
                log.warning(f"[context] Failed to update char_memory after consolidation: {e}")

    log.info(f"[context] Rolling summary updated: {len(to_absorb)} messages absorbed")
    return {"summary": new_summary, "summarized_until": new_until}


def get_rolling_summary_block(db_fn, chat_id):
    """Bloc texte du resume roulant, pret a injecter dans le prompt systeme. Vide si aucun
    resume n'existe encore pour ce chat."""
    with db_fn() as c:
        s = get_chat_summary(c, chat_id)
    if not s.get("summary"):
        return ""
    return "\n\n[Rolling conversation summary]\n" + s["summary"]


def get_reply_style_instruction(response_max_tokens):
    """Instruction de style courte selon la longueur de reponse choisie (slider chat). Ne
    sert qu'a guider le STYLE -- la vraie protection technique reste la limite de tokens
    elle-meme. Utilisee UNIQUEMENT pour les conversations normales (engine.llm_chat), jamais
    pour les taches utilitys/JSON/memoire/resumes/prompts image."""
    if response_max_tokens <= 125:
        return ("Keep replies very brief, direct and natural. Answer completely within the "
                "available space. Prioritize the essential point and avoid unnecessary "
                "introductions, repetition or long lists.")
    if response_max_tokens <= 275:
        return ("Keep replies concise, natural and conversational. Answer completely within "
                "the available space. Give enough detail without overexplaining or repeating yourself.")
    if response_max_tokens <= 425:
        return ("Give clear, moderately detailed replies. Answer completely within the available "
                "space. Expand when useful, but avoid unnecessary repetition or long introductions.")
    return ("Give thorough, well-structured replies when useful. Stay coherent and complete "
            "within the available space. Do not become repetitive or overly verbose.")


# --------------------------------------------------------------------------- #
#  Déclenchement différé (debounce N secondes d'inactivité). Jamais de LLM
#  utility synchrone après chaque message ; le cas "synchrone unique si
#  indispensable avant une réponse" est géré directement par l'appelant (app.py).
# --------------------------------------------------------------------------- #
_pending_timers = {}   # {chat_id: threading.Timer}
_pending_lock = threading.Lock()


def schedule_compaction(chat_id, idle_seconds, run_fn):
    """Planifie une consolidation differee apres idle_seconds d'inactivite. Si un nouveau
    message arrive avant ce delai (nouvel appel a schedule_compaction pour le meme chat),
    annule le timer precedent et reprogramme -- jamais deux consolidations en parallele
    pour le meme chat, et jamais de consolidation tant que la conversation reste active."""
    with _pending_lock:
        existing = _pending_timers.get(chat_id)
        if existing is not None:
            existing.cancel()
            log.info("[context] Consolidation canceled: new message received")
        timer = threading.Timer(idle_seconds, _run_compaction_safely, args=(chat_id, run_fn))
        timer.daemon = True
        _pending_timers[chat_id] = timer
        timer.start()
    log.info(f"[context] Consolidation scheduled in {idle_seconds:.0f} s")


def _run_compaction_safely(chat_id, run_fn):
    with _pending_lock:
        _pending_timers.pop(chat_id, None)
    try:
        run_fn()
    except Exception as e:  # noqa: BLE001
        log.warning(f"[context] Deferred consolidation failed (chat {chat_id}) : {e}")


def cancel_pending_compaction(chat_id):
    with _pending_lock:
        existing = _pending_timers.pop(chat_id, None)
        if existing is not None:
            existing.cancel()
