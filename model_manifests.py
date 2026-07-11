# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
model_manifests.py — manifestes des familles de workflow image.

Chaque famille (SD1.5, SDXL, Flux, Flux Klein, Z-Image, Wan/vidéo, LTX/vidéo, personnalisé)
déclare :
  - les composants qu'elle requiert (checkpoint OU unet+clip+vae séparés, lora, controlnet...)
  - les class_type ComfyUI correspondant à chaque composant (pour la detection et l'injection)
  - les formats de fichiers acceptés par composant
  - les jetons texte que le moteur sait injecter dans un workflow de cette famille
  - les dossiers de catalogue pertinents (pour filtrer la bibliotheque de modeles)

C'est le SEUL endroit qui decide quels composants un workflow d'une famille donnee peut afficher
et remplacer. L'application ne reecrit jamais un graphe ComfyUI au-dela de ce qui est declare ici :
si un node n'est pas dans COMPONENT_NODE_TYPES pour la famille, l'app n'y touche pas.

Pour ajouter une famille : ajoute une entree dans FAMILIES ci-dessous. Pour ajouter un workflow a
une famille existante : depose le .json dans workflows/<famille>/ et declare-le dans
WORKFLOW_REGISTRY (voir en bas de fichier) avec son manifeste de jetons/champs modifiables.
"""

# --------------------------------------------------------------------------- #
#  Types de composants génériques (vocabulaire commun à toutes les familles)
# --------------------------------------------------------------------------- #
COMPONENT_KINDS = (
    "checkpoint",   # modele tout-en-un (SD1.5, SDXL) : unet+clip+vae fusionnes
    "unet",         # modele de diffusion seul (Flux, Flux Klein, Z-Image, Wan, LTX)
    "clip",         # encodeur de texte (CLIP, T5, Qwen...)
    "vae",          # decodeur latent -> pixels
    "lora",         # adaptateur LoRA
    "controlnet",   # ControlNet (optionnel selon famille)
    "video_model",  # modele video dedie (Wan, LTX)
)

# Extensions de fichier acceptees par type de composant (utilise par le catalogue, section 2)
EXTENSIONS_BY_KIND = {
    "checkpoint": (".safetensors", ".ckpt"),
    "unet": (".safetensors", ".gguf", ".sft"),
    "clip": (".safetensors", ".gguf"),
    "vae": (".safetensors", ".pt"),
    "lora": (".safetensors", ".pt"),
    "controlnet": (".safetensors", ".pth"),
    "video_model": (".safetensors", ".gguf"),
}

# class_type ComfyUI qui chargent chaque type de composant (utilise pour detecter/injecter
# dans un graphe, et pour interroger /object_info afin de savoir si le node existe vraiment
# dans l'installation ComfyUI de l'utilisateur).
NODE_TYPES_BY_KIND = {
    "checkpoint": ("CheckpointLoaderSimple", "CheckpointLoader"),
    "unet": ("UnetLoaderGGUF", "UNETLoader"),
    "clip": ("CLIPLoader", "DualCLIPLoader", "CLIPLoaderGGUF"),
    "vae": ("VAELoader",),
    "lora": ("LoraLoader", "LoraLoaderModelOnly"),
    "controlnet": ("ControlNetLoader", "ControlNetApply", "ControlNetApplyAdvanced"),
    "video_model": ("UnetLoaderGGUF", "UNETLoader"),
}

# --------------------------------------------------------------------------- #
#  Constantes globales Flux 2 Klein
# --------------------------------------------------------------------------- #
# Source unique de vérité pour la correspondance workflow GGUF ↔ Safetensors.
# Utiliser model_manifests.FLUX2_WORKFLOW_VARIANTS partout — ne pas dupliquer.
FLUX2_WORKFLOW_VARIANTS = {
    "gguf": {
        "t2i":     "t2i.json",
        "i2i":     "i2i.json",
        "preview": "preview.json",
        "duo":     "duo.json",
        "trio":    "trio.json",
        "group4":  "group4.json",
    },
    "safetensors": {
        "t2i":     "t2i_st.json",
        "i2i":     "i2i_st.json",
        "preview": "preview_st.json",
        "duo":     "duo_st.json",
        "trio":    "trio_st.json",
        "group4":  "group4_st.json",
    },
}

LORA_SLOT_PRIMARY   = "301"  # ID node LoRA principal dans les workflows Flux / Krea
LORA_SLOT_SECONDARY = "302"  # ID node LoRA secondaire dans les workflows Flux / Krea
LORA_SLOT_TERTIARY  = "303"  # ID node LoRA tertiaire dans le workflow Krea 2

# --------------------------------------------------------------------------- #
#  Constantes globales Krea 2
# --------------------------------------------------------------------------- #
# Workflow unifié Krea 2 : UN SEUL fichier pour tous les usages (avatar, conversation,
# aperçus de templates, aperçus LoRA, studio). Les variations (steps réduits, résolution
# d'aperçu) sont des paramètres injectés au runtime, jamais des fichiers séparés.
# Krea 2 utilise 3 slots LoRA pré-déclarés :
# 301 personnage principal, 302 personnage secondaire/user persona, 303 utilitaire.
# Bypass par retrait + recâblage, jamais lora_name="".
KREA2_WORKFLOW = "krea2/krea2_unified.json"

#  Familles
# --------------------------------------------------------------------------- #
# "components": liste ordonnee des composants que l'UI doit afficher pour cette famille,
#   chacun avec : kind (cf COMPONENT_KINDS), label (affiche), required (bool), token (jeton
#   texte dans le workflow pour le nom de fichier, optionnel si injection par class_type)
# "settings_keys": mapping composant -> cle de reglage globale (compat avec l'existant :
#   img_unet/img_clip/img_vae restent les cles pour la famille flux2 actuelle)
FAMILIES = {
    "sd15": {
        "label": "SD 1.5",
        "is_video": False,
        "components": [
            {"kind": "checkpoint", "label": "Checkpoint", "required": True, "setting": "sd15_checkpoint"},
            {"kind": "vae", "label": "VAE (optionnel, sinon celui du checkpoint)", "required": False, "setting": "sd15_vae"},
            {"kind": "lora", "label": "LoRA", "required": False, "setting": "sd15_loras", "multi": True},
        ],
    },
    "sdxl": {
        "label": "SDXL",
        "is_video": False,
        "components": [
            {"kind": "checkpoint", "label": "Checkpoint SDXL", "required": True, "setting": "sdxl_checkpoint"},
            {"kind": "vae", "label": "VAE (optionnel, sinon celui du checkpoint)", "required": False, "setting": "sdxl_vae"},
            {"kind": "lora", "label": "LoRA", "required": False, "setting": "sdxl_loras", "multi": True},
        ],
    },
    "flux": {
        "label": "Flux",
        "is_video": False,
        "components": [
            {"kind": "unet", "label": "Modèle Flux (UNet)", "required": True, "setting": "flux_unet"},
            {"kind": "clip", "label": "CLIP / T5", "required": True, "setting": "flux_clip"},
            {"kind": "vae", "label": "VAE", "required": True, "setting": "flux_vae"},
            {"kind": "lora", "label": "LoRA", "required": False, "setting": "flux_loras", "multi": True},
        ],
    },
    "flux2_klein": {
        "label": "Flux Klein (Flux.2)",
        "is_video": False,
        # Deux modes de chargement UNet (flux2_loader_mode = "gguf" | "safetensors") :
        #   "gguf"        → UnetLoaderGGUF, réglage img_unet_gguf,        workflows *.json
        #   "safetensors" → UNETLoader,     réglage img_unet_safetensors, workflows *_st.json
        # Les deux composants UNet ont kind="unet" (type réel du catalogue).
        # La distinction se fait sur le champ "ext" (.gguf / .safetensors) et le node_type.
        # CLIP et VAE communs aux deux modes. Slots LoRA 301 et 302 inchangés.
        "loader_modes": ["gguf", "safetensors"],
        "components": [
            {"kind": "unet", "label": "UNet GGUF",        "required": False,
             "setting": "img_unet_gguf",         "node_type": "UnetLoaderGGUF",
             "ext": ".gguf",         "mode": "gguf"},
            {"kind": "unet", "label": "UNet Safetensors", "required": False,
             "setting": "img_unet_safetensors",  "node_type": "UNETLoader",
             "ext": ".safetensors",  "mode": "safetensors"},
            {"kind": "clip", "label": "CLIP / Encodeur texte", "required": True, "setting": "img_clip"},
            {"kind": "vae",  "label": "VAE",                   "required": True, "setting": "img_vae"},
            {"kind": "lora", "label": "LoRA", "required": False, "setting": "loras", "multi": True},
        ],
    },
    "krea2": {
        "label": "Krea 2",
        "is_video": False,
        # Workflow unifié unique (KREA2_WORKFLOW). Modèle de diffusion sélectionnable
        # (Krea 2 Turbo, Krea 2 Raw, ou tout .safetensors compatible détecté).
        # LoRA : gérés par les slots dédiés 301 (personnage) et 302 (utilitaire) du
        # workflow, pilotés par les réglages krea2_char_lora / krea2_util_lora —
        # PAS par la pile LoRA globale "loras" (sémantique différente : 2 slots
        # explicites avec forces indépendantes). Donc aucun composant "lora" ici.
        "components": [
            {"kind": "unet", "label": "Krea 2 diffusion model", "required": True,
             "setting": "krea2_unet", "node_type": "UNETLoader", "ext": ".safetensors"},
            {"kind": "clip", "label": "Text encoder (CLIP krea2)", "required": True,
             "setting": "krea2_clip", "ext": ".safetensors"},
            {"kind": "vae",  "label": "VAE", "required": True, "setting": "krea2_vae",
             "ext": ".safetensors"},
        ],
    },
    "zimage": {
        "label": "Z-Image",
        "is_video": False,
        "components": [
            {"kind": "unet", "label": "Modèle Z-Image", "required": True, "setting": "zimage_unet"},
            {"kind": "vae", "label": "VAE", "required": True, "setting": "zimage_vae"},
        ],
    },
    "wan_video": {
        "label": "Wan (vidéo)",
        "is_video": True,
        "components": [
            {"kind": "video_model", "label": "Modèle vidéo Wan", "required": True, "setting": "wan_model"},
            {"kind": "clip", "label": "Encodeur texte", "required": True, "setting": "wan_clip"},
            {"kind": "vae", "label": "VAE vidéo", "required": True, "setting": "wan_vae"},
        ],
    },
    "ltx_video": {
        "label": "LTX (vidéo)",
        "is_video": True,
        "components": [
            {"kind": "video_model", "label": "Modèle vidéo LTX", "required": True, "setting": "ltx_model"},
            {"kind": "clip", "label": "Encodeur texte", "required": True, "setting": "ltx_clip"},
            {"kind": "vae", "label": "VAE vidéo", "required": True, "setting": "ltx_vae"},
        ],
    },
    "custom": {
        "label": "Workflow personnalisé",
        "is_video": False,
        # Pas de composants imposes : un workflow custom declare lui-meme ses jetons
        # dans son entree WORKFLOW_REGISTRY (token_map), sans validation de famille.
        "components": [],
    },
}


def get_family(family_id):
    return FAMILIES.get(family_id)


def list_families():
    return [{"id": fid, **{k: v for k, v in f.items() if k != "components"},
             "components": f["components"]} for fid, f in FAMILIES.items()]


# --------------------------------------------------------------------------- #
#  Étape 2 — Mapping slot LoRA par famille (documentation + inspection)
#
#  AmiorAI injecte des noeuds LoraLoader DYNAMIQUEMENT (avant envoi à ComfyUI),
#  en se branchant sur le loader modèle existant. Les workflows JSON n'ont pas
#  besoin d'un slot LoRA statique : l'injection est transparente.
#
#  Bypass : si aucune LoRA n'est active, _inject_loras retourne le workflow
#  tel quel. Aucun noeud fantôme, aucune erreur.
# --------------------------------------------------------------------------- #

LORA_SLOT_MAP = {
    "flux2_klein": {
        "loader_node_types": ("UnetLoaderGGUF", "UNETLoader"),
        "clip_node_types":   ("CLIPLoader", "DualCLIPLoader", "CLIPLoaderGGUF"),
        "lora_node_type":    "LoraLoaderModelOnly",
        "model_slot": 0, "clip_slot": None, "bypass_if_empty": True,
        "notes": "Injection dynamique. UnetLoaderGGUF → [LoraLoaderModelOnly]* → consommateurs.",
    },
    "flux": {
        "loader_node_types": ("UnetLoaderGGUF", "UNETLoader"),
        "clip_node_types":   ("CLIPLoader", "DualCLIPLoader", "CLIPLoaderGGUF"),
        "lora_node_type":    "LoraLoader",
        "model_slot": 0, "clip_slot": 1, "bypass_if_empty": True,
        "notes": "Injection dynamique avec CLIP branché si CLIPLoader présent.",
    },
    "sdxl": {
        "loader_node_types": ("CheckpointLoaderSimple", "CheckpointLoader"),
        "clip_node_types":   (),
        "lora_node_type":    "LoraLoader",
        "model_slot": 0, "clip_slot": 1, "bypass_if_empty": True,
        "notes": "CheckpointLoader → [LoraLoader]* → consommateurs (model+clip).",
    },
    "sd15": {
        "loader_node_types": ("CheckpointLoaderSimple", "CheckpointLoader"),
        "clip_node_types":   (),
        "lora_node_type":    "LoraLoader",
        "model_slot": 0, "clip_slot": 1, "bypass_if_empty": True,
        "notes": "Identique SDXL. model et clip chaînés ensemble.",
    },
    "zimage": {
        "loader_node_types": ("UNETLoader", "UnetLoaderGGUF"),
        "clip_node_types":   (),
        "lora_node_type":    "LoraLoaderModelOnly",
        "model_slot": 0, "clip_slot": None, "bypass_if_empty": True,
        "notes": "Model only, pas de CLIP séparé dans la chaîne.",
    },
}


def get_lora_slot_info(family_id):
    """Retourne la description du slot LoRA pour une famille donnée,
    ou None si la famille ne supporte pas les LoRA (vidéo, custom)."""
    return LORA_SLOT_MAP.get(family_id)


# --------------------------------------------------------------------------- #
#  Registre des workflows : quel fichier appartient a quelle famille, quel usage,
#  et quels jetons texte il expose (compatible avec le mecanisme %PROMPT%/%IMAGE%
#  deja utilise par engine.py - on ne change pas ce mecanisme, on le decrit).
# --------------------------------------------------------------------------- #
# "tokens": jetons texte presents dans le fichier JSON (substitution brute, comme aujourd'hui)
# "refs": nombre de references image attendues (0 = texte-vers-image pur)
# "usage": role dans l'appli (avatar, solo, duo, trio, group, preview, ou None si juste catalogue)
# --------------------------------------------------------------------------- #
#  Registre des workflows : famille, usage, jetons texte, et slot LoRA natif.
#
#  Champ "lora_slots" (liste ordonnée des slots LoRA intégrés dans le graphe) :
#
#    supports_lora    : bool — True si le workflow a au moins un slot LoRA câblé
#    max_active_loras : int  — nombre maximum de LoRA activables (2 pour Flux2 Klein)
#    lora_slots       : list de dicts décrivant chaque slot :
#      slot           : "primary" | "secondary"
#      node_id        : str  — ID ComfyUI du node LoraLoader
#      node_type      : str  — class_type ComfyUI
#      lora_name_input, model_strength_input, clip_strength_input : noms des champs
#      bypass_strategy: "rewire" — node retiré et consommateurs recâblés si pas de LoRA
#
#  Rétrocompatibilité : "lora_slot" (ancien champ singulier) est ignoré si "lora_slots"
#  est présent. Les fonctions d'accès exposent toujours une liste.
# --------------------------------------------------------------------------- #

_FLUX2_KLEIN_SLOT_PRIMARY = {
    "slot":                 "primary",
    "node_id":              "301",
    "node_type":            "LoraLoader",
    "lora_name_input":      "lora_name",
    "model_strength_input": "strength_model",
    "clip_strength_input":  "strength_clip",
    "bypass_strategy":      "rewire",
}

_FLUX2_KLEIN_SLOT_SECONDARY = {
    "slot":                 "secondary",
    "node_id":              "302",
    "node_type":            "LoraLoader",
    "lora_name_input":      "lora_name",
    "model_strength_input": "strength_model",
    "clip_strength_input":  "strength_clip",
    "bypass_strategy":      "rewire",
}

_KREA2_SLOT_CHARACTER_1 = {
    "slot":                 "character_1",
    "node_id":              "301",
    "node_type":            "LoraLoader",
    "lora_name_input":      "lora_name",
    "model_strength_input": "strength_model",
    "clip_strength_input":  "strength_clip",
    "bypass_strategy":      "rewire",
}

_KREA2_SLOT_CHARACTER_2 = {
    "slot":                 "character_2",
    "node_id":              "302",
    "node_type":            "LoraLoader",
    "lora_name_input":      "lora_name",
    "model_strength_input": "strength_model",
    "clip_strength_input":  "strength_clip",
    "bypass_strategy":      "rewire",
}

_KREA2_SLOT_UTILITY = {
    "slot":                 "utility",
    "node_id":              "303",
    "node_type":            "LoraLoader",
    "lora_name_input":      "lora_name",
    "model_strength_input": "strength_model",
    "clip_strength_input":  "strength_clip",
    "bypass_strategy":      "rewire",
}

_KREA2_LORA_DECL = {
    "supports_lora":    True,
    "max_active_loras": 3,
    "lora_slots": [_KREA2_SLOT_CHARACTER_1, _KREA2_SLOT_CHARACTER_2, _KREA2_SLOT_UTILITY],
}

_FLUX2_KLEIN_LORA_DECL = {
    "supports_lora":    True,
    "max_active_loras": 2,
    "lora_slots": [_FLUX2_KLEIN_SLOT_PRIMARY, _FLUX2_KLEIN_SLOT_SECONDARY],
    # Ancien champ singulier conservé pour compatibilité avec code non migré
    "lora_slot": {
        "supports_lora":        True,
        "lora_node_id":         "301",
        "lora_node_type":       "LoraLoader",
        "lora_name_input":      "lora_name",
        "model_strength_input": "strength_model",
        "clip_strength_input":  "strength_clip",
        "bypass_strategy":      "rewire",
    },
}

# Alias court utilisé dans WORKFLOW_REGISTRY
_FLUX2_KLEIN_LORA_SLOT = _FLUX2_KLEIN_LORA_DECL["lora_slot"]

WORKFLOW_REGISTRY = {
    # --- Famille flux2_klein : deux slots LoRA natifs (nodes 301 + 302) ---
    "t2i.json": {
        "family": "flux2_klein", "label": "Avatar (texte → image)", "usage": "avatar",
        "refs": 0, "tokens": ["%PROMPT%", "%NEGATIVE%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "i2i.json": {
        "family": "flux2_klein", "label": "Solo (édition image)", "usage": "solo",
        "refs": 1, "tokens": ["%PROMPT%", "%NEGATIVE%", "%IMAGE%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "duo.json": {
        "family": "flux2_klein", "label": "Duo (2 références)", "usage": "duo",
        "refs": 2, "tokens": ["%PROMPT%", "%NEGATIVE%", "%IMAGE1%", "%IMAGE2%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "trio.json": {
        "family": "flux2_klein", "label": "Trio (3 références + fond)", "usage": "trio",
        "refs": 3, "tokens": ["%PROMPT%", "%NEGATIVE%", "%IMAGE1%", "%IMAGE2%", "%IMAGE3%", "%BACKGROUND%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "group4.json": {
        "family": "flux2_klein", "label": "Groupe (4 références)", "usage": "group",
        "refs": 4, "tokens": ["%PROMPT%", "%NEGATIVE%", "%IMAGE1%", "%IMAGE2%", "%IMAGE3%", "%IMAGE4%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "preview.json": {
        "family": "flux2_klein", "label": "Aperçu rapide (512×512)", "usage": "preview",
        "refs": 0, "tokens": ["%PROMPT%", "%NEGATIVE%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    # --- Famille krea2 : workflow unifié unique, slots LoRA natifs 301 + 302 + 303 ---
    # 301 = personnage principal, 302 = personnage secondaire/user persona, 303 = utilitaire.
    # Ordre : modèle de base → 301 → 302 → 303.
    # Pas de %NEGATIVE% : le négatif est un ConditioningZeroOut (cfg=1, standard Krea 2).
    KREA2_WORKFLOW: {
        "family": "krea2", "label": "Krea 2 Unified", "usage": "avatar",
        "refs": 0, "tokens": ["%PROMPT%"],
        **_KREA2_LORA_DECL,
    },
    # --- Famille sdxl : pas encore de slot déclaré ---
    "sdxl/t2i_sdxl.json": {
        "family": "sdxl", "label": "SDXL — texte vers image", "usage": "avatar",
        "refs": 0, "tokens": ["%PROMPT%", "%NEGATIVE%"],
    },
    # --- Famille sd15 : pas encore de slot déclaré ---
    "sd15/t2i_sd15.json": {
        "family": "sd15", "label": "SD 1.5 — texte vers image", "usage": "avatar",
        "refs": 0, "tokens": ["%PROMPT%", "%NEGATIVE%"],
    },
    # --- Variantes Safetensors Flux 2 Klein (UNETLoader, même slots LoRA) ---
    "t2i_st.json": {
        "family": "flux2_klein", "label": "Avatar T2I (Safetensors)", "usage": "avatar",
        "refs": 0, "tokens": ["%PROMPT%", "%NEGATIVE%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "i2i_st.json": {
        "family": "flux2_klein", "label": "Solo I2I (Safetensors)", "usage": "solo",
        "refs": 1, "tokens": ["%PROMPT%", "%NEGATIVE%", "%IMAGE%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "duo_st.json": {
        "family": "flux2_klein", "label": "Duo (Safetensors)", "usage": "duo",
        "refs": 2, "tokens": ["%PROMPT%", "%NEGATIVE%", "%IMAGE1%", "%IMAGE2%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "trio_st.json": {
        "family": "flux2_klein", "label": "Trio (Safetensors)", "usage": "trio",
        "refs": 3, "tokens": ["%PROMPT%", "%NEGATIVE%", "%IMAGE1%", "%IMAGE2%", "%IMAGE3%", "%BACKGROUND%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "group4_st.json": {
        "family": "flux2_klein", "label": "Groupe 4 (Safetensors)", "usage": "group",
        "refs": 4, "tokens": ["%PROMPT%", "%NEGATIVE%", "%IMAGE1%", "%IMAGE2%", "%IMAGE3%", "%IMAGE4%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
    "preview_st.json": {
        "family": "flux2_klein", "label": "Aperçu (Safetensors)", "usage": "preview",
        "refs": 0, "tokens": ["%PROMPT%", "%NEGATIVE%"],
        **_FLUX2_KLEIN_LORA_DECL,
    },
}


def workflows_for_family(family_id):
    return {k: v for k, v in WORKFLOW_REGISTRY.items() if v["family"] == family_id}


def get_workflow_manifest(rel_path):
    return WORKFLOW_REGISTRY.get(rel_path)


def get_lora_slot_info_from_manifest(manifest):
    """Rétrocompatibilité : retourne le slot singulier (primary) pour le code non migré."""
    if not manifest:
        return None
    slot = manifest.get("lora_slot")
    if not slot or not slot.get("supports_lora"):
        return None
    return slot


def get_lora_slots_from_manifest(manifest):
    """Retourne la liste ordonnée des slots LoRA déclarés dans le manifest.
    Slot primaire en index 0, secondaire en index 1 si disponible.
    Retourne [] si le manifest ne supporte pas les LoRA."""
    if not manifest:
        return []
    if not manifest.get("supports_lora"):
        return []
    return manifest.get("lora_slots", [])


def get_max_active_loras(manifest) -> int:
    """Nombre maximum de LoRA simultanées pour ce workflow."""
    if not manifest:
        return 0
    return manifest.get("max_active_loras", 1 if manifest.get("supports_lora") else 0)
