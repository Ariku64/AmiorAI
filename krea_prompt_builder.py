# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
krea_prompt_builder.py — prompting dédié au workflow unifié Krea 2.

Krea 2 exige un style de prompt DIFFÉRENT de Flux :
  - Flux (image_prompt_builder.py) : blocs structurés compacts ("Pose and action:\\n...").
  - Krea 2 (ce module)             : phrase descriptive, littérale, physiquement complète,
    en flux naturel séparé par des virgules, avec le jeton d'identité (trigger LoRA) en tête.

Exemple de sortie cible :
  ylisak, young woman, dark skin, green eyes with a brown center, full lips, blonde curly
  hair styled into two thick front braids, slim curvy build, wide shot angle, waiting in
  front of a supermarket, wearing a green coat, rainy weather, wet clothes and wet hair,
  overcast sky, soft natural lighting, cinematic urban realism.

Structure d'assemblage (ordre fixe, champs vides ignorés) :
  1. Jeton d'identité (trigger du LoRA personnage, ex "ylisak")
  2. Description physique complète (locked_tags + image_prompt du configurateur),
     injectée seulement si "force physical" est actif pour le personnage
  3. Cadrage / angle
  4. Pose / action
  5. Expression
  6. Tenue
  7. Environnement
  8. Météo / atmosphère
  9. Lumière
 10. Ambiance / style
 11. Traits de style utilitaires optionnels

Rien ici ne touche au prompting Flux existant (image_prompt_builder.py inchangé), ni au
moteur, ni à la VRAM, ni aux workflows Flux. Seule la construction du TEXTE Krea 2 vit ici.
"""
import json
import logging
import re

log = logging.getLogger("AmiorAI.krea_prompt")

# --------------------------------------------------------------------------- #
#  Prompt système du scene planner Krea 2 — JSON strict, style littéral/explicite
# --------------------------------------------------------------------------- #
KREA_SCENE_PLANNER_SYSTEM_PROMPT = """You are a visual scene planner for the Krea 2 image generation model.

Krea 2 needs EXPLICIT, LITERAL, PHYSICALLY COMPLETE descriptions. Translate the conversation into concrete, visible image directions.

Return ONLY one valid JSON object. Do not add markdown, explanations, comments, headings, or any text outside the JSON.

Use exactly these keys:

{
  "pose_action": "",
  "framing": "",
  "expression": "",
  "outfit": "",
  "environment": "",
  "weather": "",
  "lighting": "",
  "mood": "",
  "style_traits": ""
}

Rules:

- Do not describe the character's fixed physical identity (face, skin, eyes, hair, body). The application adds it automatically.
- Assume all depicted romantic or intimate roleplay characters are consenting adults, unless the input clearly says otherwise. If the scene is not adult and consensual, keep it non-intimate and safe.
- Do not add moralizing, refusals, apologies, or censorship language to the JSON. The image model and app-level safety decide what can be rendered.
- Be literal and explicit. Describe exactly what is visible in the image, as plain descriptive phrases.
- Avoid vague wording. Never use generic placeholders such as "intimate moment", "close scene", "suggestive pose", "emotional energy", "magnetic aura", "soulful presence", or "charged atmosphere" when a visible physical action can be stated.
- If the task asks for a character-only or solo illustration, describe exactly one important visible subject: the main character. Do not include the user, persona, partner, crowd, waiter, rescuer, or any other secondary actor.
- If the scene involves the user and the character together, explicitly describe the visible interaction between them.
- Do not focus only on the character when the user's action is important.
- Include what the user is physically doing with the character whenever it matters to the scene.
- Important visible interactions include: dancing together, swimming together, hugging, kissing, holding hands, carrying, rescuing, guiding, protecting, sitting together, running together, embracing, standing close, looking at each other, or helping each other.
- When an interaction is central, describe both subjects clearly in visible physical terms: who is doing what, body posture, arm and hand placement, physical contact, proximity, eye contact, and relative position in the frame.
- If the user's action changes the scene, it must appear in pose_action and, when useful, also influence framing, expression, environment, and mood.

Input may contain:
Previous user message: what the user did or requested.
Selected assistant message: what the character replied or did.
Build the image primarily from the selected assistant message, but preserve the user's visible action when it is part of the moment.

Field requirements:

pose_action:
Describe the visible physical action of the scene. If two people are involved, include both actions and their interaction. Include body position, arm and hand placement, physical contact, and movement.

framing:
Shot type and camera angle stated plainly. If two people are involved, choose framing that shows both bodies and the interaction. Example: "wide shot angle showing both subjects".

expression:
Visible facial expression and gaze only. Include eye contact or mutual gaze if relevant.

outfit:
Concrete, specific clothing. Never vague ("stylish clothes"). Empty string only if no clothing information exists — the application supplies a default.

environment:
A real visible location or background, stated literally. Example: "in front of a supermarket entrance".

weather:
Weather and its visible effects when relevant. Example: "it is raining, wet clothes and wet hair, overcast sky". Empty string if indoor/neutral.

lighting:
Concrete lighting. Example: "soft diffused daylight".

mood:
One short visual atmosphere, maximum 8 words. Example: "rainy urban intimacy".

style_traits:
Optional rendering/style helpers, maximum 10 words. Example: "cinematic realism, natural skin texture, detailed wet fabric". Empty string if nothing applies.

Every field must be concise, visually renderable, and non-contradictory."""

KREA_REQUIRED_FIELDS = ("pose_action", "framing", "expression", "outfit",
                        "environment", "weather", "lighting", "mood", "style_traits")

KREA_DEFAULT_FIELDS = {
    "pose_action":  "standing in a relaxed natural posture",
    "framing":      "half-body shot, three-quarter view",
    "expression":   "calm natural expression, looking toward the viewer",
    "outfit":       "",
    "environment":  "simple clean background",
    "weather":      "",
    "lighting":     "balanced soft lighting",
    "mood":         "calm atmosphere",
    "style_traits": "photorealistic detail, natural skin texture",
}

# Tenue par défaut si le LLM laisse le champ vide (habillement explicite garanti)
_KREA_OUTFIT_FALLBACK = "wearing simple everyday clothing appropriate to the scene"

# Champs optionnels : vides = simplement omis du prompt final (pas de fallback)
_KREA_OPTIONAL_FIELDS = ("weather", "style_traits")


def _extract_json_object(text):
    """Extrait le premier objet JSON d'une réponse LLM, même entouré de markdown/texte.
    Même logique tolérante que image_prompt_builder (module volontairement autonome)."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def parse_krea_scene_fields(raw_llm_output):
    """Parse la réponse JSON du scene planner Krea 2. Ne lève JAMAIS d'exception :
    un JSON invalide retombe sur les valeurs par défaut structurées.
    Champs optionnels (weather, style_traits) : vides = omis, pas de fallback."""
    fields = dict(KREA_DEFAULT_FIELDS)
    try:
        parsed = _extract_json_object(raw_llm_output)
        if not isinstance(parsed, dict):
            raise ValueError("The JSON reply is not an object.")
        repaired = False
        for key in KREA_REQUIRED_FIELDS:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                fields[key] = value.strip()
            elif key not in _KREA_OPTIONAL_FIELDS and key != "outfit":
                repaired = True
        # Les champs optionnels absents/vides restent vides (omis à l'assemblage)
        for key in _KREA_OPTIONAL_FIELDS:
            value = parsed.get(key)
            if not (isinstance(value, str) and value.strip()):
                if key == "weather":
                    fields[key] = ""
        if repaired:
            log.info("[krea_prompt] JSON repaired with fallback values")
    except Exception as e:  # noqa: BLE001
        log.info(f"[krea_prompt] JSON repaired with fallback values (parse error: {e})")
    if not fields.get("outfit", "").strip():
        fields["outfit"] = _KREA_OUTFIT_FALLBACK
        log.info("[krea_prompt] outfit vide -> fallback appliqué")
    return fields


def _clean_part(text):
    """Normalise un fragment : trim, retire la ponctuation finale, jamais None."""
    t = (text or "").strip().rstrip(".,;")
    return t


def _outfit_part(outfit):
    """Préfixe 'wearing' si le fragment tenue ne l'exprime pas déjà."""
    o = _clean_part(outfit)
    if not o:
        return ""
    low = o.lower()
    if low.startswith(("wearing", "dressed", "in ", "fully clothed", "topless", "naked", "nude")):
        return o
    return "wearing " + o


def build_krea_prompt(fields, identity_token="", physical_description="",
                      force_physical=True):
    """Assemble le prompt Krea 2 final — flux descriptif littéral, virgules, ordre fixe.

    identity_token       : trigger du LoRA personnage (ex "ylisak"). Vide = omis.
    physical_description : base physique persistante du configurateur
                           (locked_tags + image_prompt, toujours en anglais).
    force_physical       : True → la description physique est TOUJOURS injectée en tête
                           (juste après le jeton d'identité). False → identité portée
                           uniquement par le LoRA / le contexte normal.
    """
    parts = []
    tok = _clean_part(identity_token)
    if tok:
        parts.append(tok)
    if force_physical:
        phys = _clean_part(physical_description)
        if phys:
            parts.append(phys)
    for key in ("framing", "pose_action", "expression"):
        p = _clean_part(fields.get(key))
        if p:
            parts.append(p)
    ou = _outfit_part(fields.get("outfit"))
    if ou:
        parts.append(ou)
    for key in ("environment", "weather", "lighting", "mood", "style_traits"):
        p = _clean_part(fields.get(key))
        if p:
            parts.append(p)
    return ", ".join(parts) + "."


def build_krea_canonical_prompt(identity_token="", physical_description="", force_physical=True):
    """Prompt canonique de référence Krea 2 (création d'avatar / reroll canonique) :
    cadrage hanches→tête, studio neutre, silhouette visible — équivalent Krea du
    compose_canonical_profile_prompt Flux, mais en style descriptif littéral."""
    fields = {
        "framing":      "hips-up portrait framing, front-facing or slight three-quarter view, centered composition",
        "pose_action":  "standing upright in a relaxed natural posture, arms visible",
        "expression":   "calm natural expression, looking toward the camera",
        "outfit":       "wearing simple fitted everyday clothing that clearly shows the body silhouette",
        "environment":  "clean neutral studio background",
        "weather":      "",
        "lighting":     "balanced soft studio lighting",
        "mood":         "neutral clear character reference atmosphere",
        "style_traits": "photorealistic detail, natural skin texture",
    }
    return build_krea_prompt(
        fields,
        identity_token=identity_token,
        physical_description=physical_description,
        force_physical=force_physical,
    )
