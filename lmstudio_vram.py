# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""LM Studio model lifecycle and VRAM coordination for AmiorAI.

Both the conversational model and the optional utility model are hosted by the same
LM Studio server. This module uses LM Studio's native model-management API to load or
unload only the models configured by AmiorAI. A dedicated re-entrant lock prevents
ComfyUI generation and LM Studio model reloads from competing for VRAM.
"""
import json
import logging
import time
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

log = logging.getLogger("AmiorAI.lmstudio_vram")

# Verrou reentrant dedie : couvre le decharge LM Studio -> toute la generation ComfyUI ->
# le rechargement LM Studio + appel texte qui suit. Une requete texte qui arrive PENDANT une
# generation image attend ici que le cycle complet soit termine avant de recharger un modele,
# ce qui evite tout conflit VRAM (image et LLM qui se chargent en meme temps).
LMSTUDIO_VRAM_LOCK = threading.RLock()

# Read-only lifecycle exposed to the UI. It reports real phases, never an invented percent.
_LIFECYCLE_STATE = {
    "state": "idle", "role": None, "model": None, "started": 0.0,
    "finished": 0.0, "error": None, "message": "",
}
_LIFECYCLE_LOCK = threading.Lock()


def _set_lifecycle(**values):
    with _LIFECYCLE_LOCK:
        _LIFECYCLE_STATE.update(values)


def lifecycle_status():
    with _LIFECYCLE_LOCK:
        state = dict(_LIFECYCLE_STATE)
    started = float(state.get("started") or 0)
    finished = float(state.get("finished") or 0)
    endpoint = finished if finished and state.get("state") in ("loaded", "unloaded", "error", "unverified") else time.time()
    state["elapsed"] = round(max(0.0, endpoint - started), 1) if started else 0
    return state


def _setting_float(settings, key, default, min_value=None, max_value=None):
    try:
        val = float(settings.get(key, default))
    except Exception:
        val = float(default)
    if min_value is not None:
        val = max(float(min_value), val)
    if max_value is not None:
        val = min(float(max_value), val)
    return val


def _setting_bool(settings, key, default=True):
    raw = settings.get(key, "true" if default else "false")
    return str(raw).lower() in ("true", "1", "yes", "oui", "on")


def _sleep_setting(settings, key, default, reason=""):
    delay = _setting_float(settings, key, default, min_value=0, max_value=60)
    if delay > 0:
        if reason:
            log.info(f"[VRAM] Pause {reason} : {delay:g} s")
        time.sleep(delay)


def _native_timeout(settings, method, path):
    # LM Studio peut accepter une requete /models/load, commencer le chargement, puis ne
    # repondre qu'apres de longues dizaines de secondes. L'ancien timeout fixe de 10 s
    # produisait donc de fausses erreurs alors que le modele finissait bien par charger.
    default = 240 if path == "/models/load" else 60
    return _setting_float(settings, "lmstudio_native_timeout", default, min_value=5, max_value=1800)


@contextmanager
def vram_lock_for_image():
    """Acquiert LMSTUDIO_VRAM_LOCK pour une generation d'image, en loggant explicitement si le
    verrou etait deja tenu (attente reelle -> probablement un appel texte LM Studio en cours)."""
    acquired_immediately = LMSTUDIO_VRAM_LOCK.acquire(blocking=False)
    if not acquired_immediately:
        log.info("[VRAM] Image generation locked: waiting for a text request")
        LMSTUDIO_VRAM_LOCK.acquire()
    try:
        yield
    finally:
        LMSTUDIO_VRAM_LOCK.release()


@contextmanager
def vram_lock_for_text(role):
    """Acquiert LMSTUDIO_VRAM_LOCK pour un appel texte LM Studio, en loggant explicitement si
    le verrou etait deja tenu (attente reelle -> tres probablement une generation image en
    cours, c'est exactement le scenario que ce verrou doit proteger)."""
    acquired_immediately = LMSTUDIO_VRAM_LOCK.acquire(blocking=False)
    if not acquired_immediately:
        log.info(f"[VRAM] Text request {role} waiting: image generation in progress")
        LMSTUDIO_VRAM_LOCK.acquire()
    try:
        yield
    finally:
        LMSTUDIO_VRAM_LOCK.release()


def _native_base(openai_base_url):
    """Derive la base de l'API native (/api/v1) depuis l'URL OpenAI-compatible configuree
    (/v1). Ex: http://127.0.0.1:1234/v1 -> http://127.0.0.1:1234/api/v1"""
    base = (openai_base_url or "http://127.0.0.1:1234/v1").strip().rstrip("/")
    if base.endswith("/api/v1"):
        root = base[: -len("/api/v1")]
    elif base.endswith("/v1"):
        root = base[: -len("/v1")]
    else:
        root = base
    return root + "/api/v1"


def _http_json(url, method="GET", payload=None, api_key="", timeout=10):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return json.loads(body.decode("utf-8")) if body else {}


def _native_request(settings, method, path, payload=None):
    """Appelle l'API native LM Studio. Leve une RuntimeError claire et explicite (jamais de
    silent fallback when the native API is unavailable."""
    openai_base = settings.get("lmstudio_url") or "http://127.0.0.1:1234/v1"
    native_base = _native_base(openai_base)
    api_key = (settings.get("lmstudio_api_key") or "").strip()
    url = native_base + path
    try:
        return _http_json(url, method=method, payload=payload, api_key=api_key,
                          timeout=_native_timeout(settings, method, path))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            raw = e.read().decode("utf-8", "replace").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    err = parsed.get("error", parsed) if isinstance(parsed, dict) else parsed
                    detail = str(err.get("message") or err.get("detail") or err) if isinstance(err, dict) else str(err)
                except Exception:
                    detail = raw[:600]
        except Exception:
            pass
        raise RuntimeError(
            f"The native LM Studio API returned HTTP {e.code} on {url}"
            + (f": {detail}" if detail else f" ({e.reason})")
            + ". Make sure LM Studio is up to date and the configured model ID is valid."
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Native LM Studio API unreachable at {url}. Make sure LM Studio is running, that "
            f"its local server is started and the native /api/v1 API is available. Details: {e}"
        )


# --------------------------------------------------------------------------- #
#  Découverte et correspondance modèle configuré -> instance chargée
# --------------------------------------------------------------------------- #
def list_native_models(settings):
    """GET /api/v1/models -- liste complete avec loaded_instances par modele."""
    data = _native_request(settings, "GET", "/models")
    return data.get("models", [])


def model_matches(model_entry, configured_id):
    """Correspondance robuste entre un modele configure dans AmiorAI (lmstudio_model ou
    llm_util_model, tel que saisi par l'utilisateur) et une entree de /api/v1/models.
    Ordre de verification, du plus fiable au plus permissif : key exacte, puis
    selected_variant exact, puis l'id d'une de ses loaded_instances. Aucune correspondance
    partielle/floue : en cas de doute, on ne matche pas (mieux vaut ne pas decharger que de
    decharger le mauvais modele)."""
    if not configured_id:
        return False
    configured_id = configured_id.strip()
    if model_entry.get("key") == configured_id:
        return True
    if model_entry.get("selected_variant") == configured_id:
        return True
    for inst in model_entry.get("loaded_instances", []):
        if inst.get("id") == configured_id:
            return True
    return False


def _find_loaded_instances(models, configured_id):
    """Renvoie la liste des instance_id actuellement chargees pour le modele configure
    correspondant a configured_id, ou [] si rien ne correspond (pas charge, ou aucune
    correspondance fiable -> ne rien decharger plutot que de se tromper)."""
    out = []
    for m in models:
        if model_matches(m, configured_id):
            for inst in m.get("loaded_instances", []):
                out.append(inst.get("id"))
    return [i for i in out if i]


# --------------------------------------------------------------------------- #
#  Déchargement (avant génération image)
# --------------------------------------------------------------------------- #
def _is_same_lmstudio_server(url_a, url_b):
    """Compare deux URLs LM Studio (conversation vs utility) en ignorant le chemin
    /v1 final, pour savoir si elles pointent vers le meme serveur natif."""
    return _native_base(url_a) == _native_base(url_b)


def applicability(settings):
    """LM Studio is the only LLM backend. Both roles use the same server."""
    util_enabled = _setting_bool(settings, "llm_util_enabled", False)
    return {
        "conversational_applicable": True,
        "utility_applicable": util_enabled,
        "applicable": True,
    }


def unload_amiorai_models(settings):
    """Decharge de LM Studio les modeles configures pour AmiorAI (conversation si le
    backend actif est lmstudio, utility si actif et sur le meme serveur), uniquement si
    lmstudio_vram_offload_enabled est actif. Ne decharge jamais un modele dont la
    correspondance est ambigue. Renvoie la liste des instance_id effectivement decharges."""
    offload_enabled = str(settings.get("lmstudio_vram_offload_enabled", "true")).lower() in ("true", "1", "yes")
    if not offload_enabled:
        return []

    appl = applicability(settings)
    if not appl["applicable"]:
        return []  # nothing to do

    _set_lifecycle(
        state="unloading", role="all", model="AmiorAI models", started=time.time(), finished=0.0,
        error=None, message="Releasing LM Studio models before image generation",
    )
    try:
        models = list_native_models(settings)
    except RuntimeError as exc:
        _set_lifecycle(
            state="error", role="all", model="AmiorAI models", finished=time.time(),
            error=str(exc), message=str(exc),
        )
        raise

    unloaded = []

    if appl["conversational_applicable"]:
        conv_model = settings.get("lmstudio_model") or ""
        for inst_id in _find_loaded_instances(models, conv_model):
            _native_request(settings, "POST", "/models/unload", {"instance_id": inst_id})
            log.info(f"[VRAM] LM Studio conversation model unloaded: {inst_id}")
            unloaded.append(inst_id)

    if appl["utility_applicable"]:
        util_model = settings.get("llm_util_model") or settings.get("lmstudio_model") or ""
        for inst_id in _find_loaded_instances(models, util_model):
            if inst_id in unloaded:
                continue  # meme instance que le conversation (modele partage) : deja faite
            _native_request(settings, "POST", "/models/unload", {"instance_id": inst_id})
            log.info(f"[VRAM] LM Studio utility model unloaded: {inst_id}")
            unloaded.append(inst_id)

    if not unloaded:
        log.info("[VRAM] No AmiorAI model loaded in LM Studio")
    else:
        _sleep_setting(settings, "lmstudio_post_unload_delay", 1.5, "stabilization after LM Studio unload")

    _set_lifecycle(
        state="unloaded", role="all", model="AmiorAI models", finished=time.time(), error=None,
        message=(f"Released {len(unloaded)} LM Studio model instance(s)" if unloaded
                 else "No AmiorAI model was loaded in LM Studio"),
    )
    return unloaded


# --------------------------------------------------------------------------- #
#  Rechargement à la demande (avant un appel texte)
# --------------------------------------------------------------------------- #
def _wait_until_loaded(settings, model_id, log_label):
    """Attend que LM Studio confirme une instance chargee pour le modele demande.
    Le POST /models/load peut revenir avant que /v1/chat/completions soit utilisable ;
    ce polling evite les erreurs transitoires "model not loaded" juste apres une bascule."""
    timeout_s = _setting_float(settings, "lmstudio_load_wait_timeout", 180, min_value=0, max_value=1800)
    if timeout_s <= 0:
        return True
    interval = _setting_float(settings, "lmstudio_load_poll_interval", 1.0, min_value=0.25, max_value=10)
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() <= deadline:
        try:
            models = list_native_models(settings)
            if _find_loaded_instances(models, model_id):
                log.info(f"[VRAM] LM Studio confirme {log_label} loaded: {model_id}")
                return True
        except RuntimeError as e:
            last_error = e
        time.sleep(interval)
    if last_error:
        log.warning(f"[VRAM] Confirmation chargement {log_label} impossible : {last_error}")
    return False


def ensure_loaded(settings, role):
    """Ensure the requested LM Studio role model is loaded before text generation."""
    reload_enabled = _setting_bool(settings, "lmstudio_reload_on_demand", True)
    if not reload_enabled:
        return

    if role == "conversation":
        model_id = (settings.get("lmstudio_model") or "").strip()
        log_label = "conversation"
    elif role == "utility":
        model_id = (settings.get("llm_util_model") or settings.get("lmstudio_model") or "").strip()
        log_label = "utility"
    else:
        return
    if not model_id:
        return

    started = time.time()
    _set_lifecycle(
        state="checking", role=role, model=model_id, started=started, finished=0.0,
        error=None, message=f"Checking LM Studio {log_label} model",
    )
    try:
        try:
            models = list_native_models(settings)
        except RuntimeError as exc:
            # Native lifecycle management is optional for the OpenAI request itself.
            log.warning(
                f"[VRAM] Unable to check LM Studio state before reloading {log_label} "
                f"(native API unreachable) — direct call without verification."
            )
            _set_lifecycle(
                state="unverified", role=role, model=model_id, finished=time.time(),
                error=str(exc), message="Native model state unavailable; using direct chat request",
            )
            return

        if _find_loaded_instances(models, model_id):
            _set_lifecycle(
                state="loaded", role=role, model=model_id, finished=time.time(), error=None,
                message=f"LM Studio {log_label} model is already loaded",
            )
            return

        log.info(f"[VRAM] Rechargement {log_label} : {model_id}")
        _set_lifecycle(
            state="loading", role=role, model=model_id, error=None,
            message=f"Loading LM Studio {log_label} model",
        )
        load_error = None
        try:
            _native_request(settings, "POST", "/models/load", {"model": model_id})
        except RuntimeError as exc:
            load_error = exc
            log.warning(f"[VRAM] Appel load {log_label} not confirmed immediately: {exc}")

        _set_lifecycle(
            state="waiting", role=role, model=model_id,
            message=f"Waiting for LM Studio to confirm {log_label} model",
        )
        confirmed = _wait_until_loaded(settings, model_id, log_label)
        if not confirmed:
            if load_error:
                raise load_error
            raise RuntimeError(
                f"LM Studio did not confirm model load for {log_label} ({model_id}) within "
                "the configured timeout. Increase lmstudio_load_wait_timeout or check the model name."
            )

        delay = _setting_float(settings, "lmstudio_post_load_delay", 4, min_value=0, max_value=60)
        if delay > 0:
            _set_lifecycle(
                state="stabilizing", role=role, model=model_id,
                message=f"LM Studio model loaded; stabilizing for {delay:g} s",
            )
            time.sleep(delay)
        _set_lifecycle(
            state="loaded", role=role, model=model_id, finished=time.time(), error=None,
            message=f"LM Studio {log_label} model is ready",
        )
    except Exception as exc:
        _set_lifecycle(
            state="error", role=role, model=model_id, finished=time.time(),
            error=str(exc), message=str(exc),
        )
        raise


# --------------------------------------------------------------------------- #
#  Bouton "Décharger maintenant" (action manuelle, ignore lmstudio_vram_offload_enabled)
# --------------------------------------------------------------------------- #
def unload_now(settings):
    """Decharge immediatement les modeles AmiorAI, sans attendre une generation d'image et
    sans dependre du reglage lmstudio_vram_offload_enabled (action manuelle explicite)."""
    forced_settings = dict(settings)
    forced_settings["lmstudio_vram_offload_enabled"] = "true"
    with LMSTUDIO_VRAM_LOCK:
        return unload_amiorai_models(forced_settings)


# --------------------------------------------------------------------------- #
#  Helpers dédiés : déchargement ciblé par rôle (Point 5)
# --------------------------------------------------------------------------- #
def roles_share_same_model(settings):
    """Return True when the optional utility role uses the same LM Studio model."""
    if not _setting_bool(settings, "llm_util_enabled", False):
        return False
    conv_model = (settings.get("lmstudio_model") or "").strip()
    util_model = (settings.get("llm_util_model") or "").strip() or conv_model
    return bool(conv_model and util_model and conv_model == util_model)


def unload_role_model(settings, role):
    """Decharge uniquement le modele d'un role donne ('conversation' ou 'utility') depuis
    LM Studio. Utilise la correspondance fiable existante (key exacte, selected_variant,
    loaded_instances). Ne decharge jamais un modele non lie a ce role. Retourne la liste
    des instance_id reellement decharges."""
    if role == "conversation":
        model_id = (settings.get("lmstudio_model") or "").strip()
        log_label = "conversation"
    elif role == "utility":
        model_id = (settings.get("llm_util_model") or settings.get("lmstudio_model") or "").strip()
        log_label = "utility"
    else:
        return []
    if not model_id:
        return []
    _set_lifecycle(
        state="unloading", role=role, model=model_id, started=time.time(), finished=0.0,
        error=None, message=f"Unloading LM Studio {log_label} model",
    )
    try:
        models = list_native_models(settings)
    except RuntimeError as e:
        log.warning(f"[VRAM] Impossible de lister les modeles LM Studio pour decharger {log_label} : {e}")
        return []
    unloaded = []
    for inst_id in _find_loaded_instances(models, model_id):
        try:
            _native_request(settings, "POST", "/models/unload", {"instance_id": inst_id})
            log.info(f"[VRAM] {log_label.capitalize()} unloaded before utility task: {inst_id}")
            unloaded.append(inst_id)
        except RuntimeError as e:
            log.warning(f"[VRAM] Unload failed {log_label} {inst_id} : {e}")
    if unloaded:
        _sleep_setting(settings, "lmstudio_post_unload_delay", 1.5, f"stabilization after unloading {log_label}")
    _set_lifecycle(
        state="unloaded", role=role, model=model_id, finished=time.time(), error=None,
        message=f"LM Studio {log_label} model unloaded" if unloaded else f"LM Studio {log_label} model was not loaded",
    )
    return unloaded
