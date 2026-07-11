# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
image_prompt_builder.py — prompting image structuré ("fill the blank").

Remplace l'ancien système où le LLM rédigeait librement un prompt image complet (style
littéraire, parfois psychologique/abstrait — mauvais pour la cohérence visuelle, surtout en
T2I). Désormais le LLM ne fait QUE remplir 7 champs visuels concrets via un JSON strict ;
c'est AmiorAI qui assemble lui-même le prompt final dans un template fixe.

Deux ancrages d'identité, jamais mélangés :
  - I2I (et groupe/persona, qui utilise plusieurs images de référence) : l'identité vient de
    l'image de référence fournie au modèle. Le LLM ne décrit jamais le physique.
  - T2I (pas d'image de référence) : l'identité vient des traits physiques verrouillés du
    personnage (locked_tags). Le LLM ne décrit jamais le physique non plus.

Rien ici ne touche à LM Studio, VRAM, ComfyUI, aux workflows, à la galerie, à l'humeur, au
TTS, à la mémoire conversationle, au LoRA, ni au pipeline de génération moteur lui-même
(generate_t2i/i2i/group) — seule la construction du TEXTE du prompt est concernée.
"""
import json
import logging
import re

log = logging.getLogger("AmiorAI.image_prompt")

# --------------------------------------------------------------------------- #
#  Prompt système du "scene planner" — impose un JSON strict, jamais de prose libre
# --------------------------------------------------------------------------- #
SCENE_PLANNER_SYSTEM_PROMPT = """You are a visual scene planner for an image generation system.

Your job is to translate the user's request into concrete, visible image directions.

Return ONLY one valid JSON object. Do not add markdown, explanations, comments, headings, or any text outside the JSON.

Use exactly these keys:

{
  "pose_action": "",
  "framing": "",
  "expression": "",
  "environment": "",
  "lighting": "",
  "mood": "",
  "outfit": ""
}

Rules:

- Do not describe the character's fixed physical identity. The application adds it automatically.
- Do not write poetic, symbolic, psychological, or invisible descriptions.
- Do not use phrases such as:
  "probing deep within your soul",
  "charged with subtle energy",
  "inviting introspection",
  "magnetic aura",
  "soulful presence",
  "close yet detached",
  "emotionally complex",
  "radiates longing".

- Translate emotional intent into visible details:
  mysterious = reserved posture, slight head tilt, unreadable direct gaze
  romantic = soft smile, warm eye contact, relaxed shoulders, intimate lighting
  sad = lowered gaze, slightly slumped shoulders, watery eyes, cool soft lighting
  confident = upright posture, direct gaze, relaxed shoulders
  shy = averted gaze, slight blush, hands close to the body
  playful = mischievous smile, raised eyebrow, relaxed asymmetrical pose

Field requirements:

pose_action:
Describe body position, posture, action, arm and hand placement when useful.

framing:
Describe visible shot type and camera angle.

expression:
Describe only visible facial expression and gaze.

environment:
Describe a real visible location or background.

lighting:
Describe concrete lighting.

mood:
One short visual atmosphere only, maximum 8 words.

outfit:
Describe clothing when requested or relevant. Use specific, concrete and visible descriptions.
Do not use vague phrases such as "seductive clothing", "revealing style" or "barely dressed vibe".
Prefer descriptions like "white linen shirt, dark jeans", "red cocktail dress", "grey hoodie and leggings".
Leave the field empty string only if no outfit information is available from the request — the application will supply a default.

Every field must be concise, visually renderable, and non-contradictory.
Never use "neutral pose" or "natural expression" when a specific pose or expression is already described."""

REQUIRED_FIELDS = ("pose_action", "framing", "expression", "environment", "lighting", "mood", "outfit")

DEFAULT_FIELDS = {
    "pose_action": "Standing in a relaxed natural posture.",
    "framing": "Half-body shot, three-quarter view.",
    "expression": "Calm natural expression, looking toward the viewer.",
    "environment": "Simple clean background.",
    "lighting": "Balanced soft lighting.",
    "mood": "Calm atmosphere.",
    "outfit": "",
}

# Valeur par défaut pour outfit quand le LLM le laisse vide ou qu'il est absent.
# Garantit qu'un niveau d'habillement explicite est toujours présent dans le prompt final.
_OUTFIT_FALLBACK = "Fully clothed, simple outfit appropriate to the scene."


def _extract_json_object(text):
    """Extrait le premier objet JSON d'une reponse LLM, meme entoure de markdown/texte.
    Duplique volontairement la logique de app.py::_extract_json (pas d'import croise) :
    meme comportement, juste local a ce module pour rester autonome."""
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


def parse_scene_fields(raw_llm_output):
    """Parse la reponse JSON du LLM scene planner. Verifie les 7 cles attendues, complete
    proprement tout champ manquant/vide avec sa valeur par defaut. Ne leve JAMAIS
    d'exception : un JSON invalide ne doit jamais faire echouer toute la generation
    d'image, juste retomber sur un fallback structure raisonnable.
    Si outfit est vide/absent apres parsing, le fallback _OUTFIT_FALLBACK est applique
    pour garantir qu'un niveau d'habillement explicite est toujours present."""
    fields = dict(DEFAULT_FIELDS)
    try:
        parsed = _extract_json_object(raw_llm_output)
        if not isinstance(parsed, dict):
            raise ValueError("The JSON reply is not an object.")
        repaired = False
        for key in REQUIRED_FIELDS:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                fields[key] = value.strip()
            elif key != "outfit":
                repaired = True
        if repaired:
            log.info("[image_prompt] JSON repaired with fallback values")
    except Exception as e:  # noqa: BLE001
        log.info(f"[image_prompt] JSON repaired with fallback values (parse error: {e})")
    # Outfit obligatoire : si vide apres parse, appliquer le fallback
    if not fields.get("outfit", "").strip():
        fields["outfit"] = _OUTFIT_FALLBACK
        log.info("[image_prompt] outfit vide -> fallback applique")
    return fields


# --------------------------------------------------------------------------- #
#  Assemblage du prompt final — template fixe, AmiorAI decide de la structure,
#  jamais le LLM. Ordre de priorite visuelle : identite > pose > cadrage >
#  expression > tenue > environnement > lumiere > ambiance.
# --------------------------------------------------------------------------- #
def _build_common_block(fields):
    """Bloc commun aux deux templates (I2I et T2I) : pose, cadrage, expression, tenue,
    environnement, lumiere, ambiance -- dans cet ordre, identique dans les deux cas. Seule
    l'ancre d'identite (prefixe) differe entre I2I et T2I.
    Outfit est TOUJOURS present : parse_scene_fields garantit qu'il n'est jamais vide."""
    parts = [
        f"Pose and action:\n{fields['pose_action']}",
        f"\nFraming:\n{fields['framing']}",
        f"\nExpression:\n{fields['expression']}",
        f"\nOutfit:\n{fields['outfit']}",
        f"\nEnvironment:\n{fields['environment']}",
        f"\nLighting:\n{fields['lighting']}",
        f"\nMood:\n{fields['mood']}",
    ]
    return "\n".join(parts)


def build_i2i_prompt(fields):
    """Template I2I (et groupe/persona, ancrage par image(s) de reference). Une seule
    instruction d'identite, jamais repetee ailleurs dans le prompt."""
    anchor = (
        "Use the supplied reference image as the identity anchor. Preserve the same face, "
        "hairstyle, skin tone, body proportions and distinctive features.\n\n"
    )
    return anchor + _build_common_block(fields)


def build_t2i_prompt(fields, hard_locked_identity):
    """Template T2I (pas d'image de reference, ancrage par traits physiques verrouilles du
    personnage). Le LLM n'a jamais decrit l'identite physique : elle vient uniquement de
    hard_locked_identity (locked_tags du personnage), injectee telle quelle ici."""
    identity = (hard_locked_identity or "").strip() or "Consistent character identity."
    anchor = (
        f"Fixed character identity:\n{identity}. These physical traits must remain "
        f"consistent and must not change.\n\n"
    )
    return anchor + _build_common_block(fields)


def build_multiref_i2i_prompt(fields, multiref_header):
    """Variante I2I pour le mode groupe/persona : prefixe le header multi-reference deja
    utilise par l'appli (ex: 'image 1 is X, image 2 is Y. keep faces consistent. N people
    in the scene:') devant le template I2I structure, plutot que devant une phrase libre."""
    return (multiref_header or "").strip() + "\n\n" + build_i2i_prompt(fields)
