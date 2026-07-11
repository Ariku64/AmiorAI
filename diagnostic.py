# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
diagnostic.py — Module de diagnostic AmiorAI.

Principe : checks non-destructifs, aucun side-effect, aucune génération.
Chaque check retourne un dict avec un statut ainsi que des clés i18n.
Le backend garde des libellés de secours pour compatibilité API, mais l'interface
traduit toujours les champs *_key côté client.
"""
import json
import os
import re
import time
import urllib.request
import urllib.error


def _anon_path(path: str) -> str:
    """Anonymise un chemin absolu pour le rapport copiable.
    Conserve les 4 derniers segments et retire l'identité utilisateur locale.
    """
    if not path:
        return ""
    p = path.replace("\\", "/")
    p = re.sub(r"^[A-Za-z]:/", "", p)
    p = re.sub(r"^(?:Users|home)/[^/]+/", "~/", p)
    parts = [x for x in p.split("/") if x]
    if len(parts) > 4:
        return ".../" + "/".join(parts[-4:])
    return "/".join(parts)


# Statuts
OK = "ok"
WARN = "warning"
ERR = "error"
SKIP = "skipped"


def _chk(
    name,
    status,
    detail,
    technical=None,
    *,
    name_key=None,
    name_vars=None,
    detail_key=None,
    detail_vars=None,
    technical_items=None,
):
    """Construit un check avec texte de secours et métadonnées de traduction.

    Les champs textuels d'origine restent présents pour les outils/API externes.
    L'interface AmiorAI utilise ``name_key`` / ``detail_key`` et les variables
    associées ; elle peut donc re-traduire un même rapport sans le relancer.
    """
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "technical": technical,
        "name_key": name_key,
        "name_vars": name_vars or {},
        "detail_key": detail_key,
        "detail_vars": detail_vars or {},
        "technical_items": technical_items or [],
    }


def _get_json(url, timeout=4):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode())


# ─────────────────────────────────────────────────────────────────────────────
# 1. Application
# ─────────────────────────────────────────────────────────────────────────────
def check_application(db_path, data_dir, wf_dir, img_dir):
    checks = []

    # SQLite
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        filename = os.path.basename(db_path)
        checks.append(_chk(
            "SQLite", OK, f"Base accessible : {filename}",
            name_key="diagnostic.checks.sqlite",
            detail_key="diagnostic.details.database_accessible",
            detail_vars={"filename": filename},
        ))
    except Exception as exc:
        checks.append(_chk(
            "SQLite", ERR, "Base de données inaccessible", str(exc),
            name_key="diagnostic.checks.sqlite",
            detail_key="diagnostic.details.database_unavailable",
        ))

    # Tables essentielles
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        essential = ["characters", "chats", "messages", "settings",
                     "model_files", "model_folders", "loras"]
        missing = [table for table in essential if table not in tables]
        if missing:
            missing_text = ", ".join(missing)
            checks.append(_chk(
                "Tables DB", WARN, f"Tables manquantes : {missing_text}",
                name_key="diagnostic.checks.database_tables",
                detail_key="diagnostic.details.tables_missing",
                detail_vars={"tables": missing_text},
            ))
        else:
            checks.append(_chk(
                "Tables DB", OK, f"{len(tables)} tables présentes",
                name_key="diagnostic.checks.database_tables",
                detail_key="diagnostic.details.tables_present",
                detail_vars={"count": len(tables)},
            ))
    except Exception as exc:
        checks.append(_chk(
            "Tables DB", ERR, "Impossible de lire les tables", str(exc),
            name_key="diagnostic.checks.database_tables",
            detail_key="diagnostic.details.tables_unreadable",
        ))

    # Répertoires
    folders = [
        ("Données", "diagnostic.checks.folder_data", data_dir),
        ("Images", "diagnostic.checks.folder_images", img_dir),
        ("Workflows", "diagnostic.checks.folder_workflows", wf_dir),
    ]
    for label, name_key, path in folders:
        anon = _anon_path(os.path.abspath(path)) if os.path.isdir(path) else _anon_path(path)
        if os.path.isdir(path):
            checks.append(_chk(
                f"Dossier {label}", OK, anon,
                name_key=name_key,
                detail_key="diagnostic.details.path_available",
                detail_vars={"path": anon},
            ))
        else:
            checks.append(_chk(
                f"Dossier {label}", ERR, f"Introuvable : {anon}",
                name_key=name_key,
                detail_key="diagnostic.details.path_missing",
                detail_vars={"path": anon},
            ))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 2. LM Studio
# ─────────────────────────────────────────────────────────────────────────────
def check_lmstudio(settings):
    checks = []
    url = (settings.get("lmstudio_url") or "").rstrip("/")
    if not url:
        return [_chk(
            "LM Studio", SKIP, "URL non configurée",
            name_key="diagnostic.checks.lmstudio",
            detail_key="diagnostic.details.url_not_configured",
        )]

    checks.append(_chk(
        "URL LM Studio", OK, url,
        name_key="diagnostic.checks.lmstudio_url",
        detail_key="diagnostic.details.value",
        detail_vars={"value": url},
    ))

    # Ping
    try:
        data = _get_json(f"{url}/models")
        models = data.get("data", [])
        checks.append(_chk(
            "LM Studio joignable", OK, f"{len(models)} modèle(s) visible(s)",
            name_key="diagnostic.checks.lmstudio_reachable",
            detail_key="diagnostic.details.models_visible",
            detail_vars={"count": len(models)},
        ))
    except Exception as exc:
        checks.append(_chk(
            "LM Studio joignable", ERR, "Serveur inaccessible", str(exc),
            name_key="diagnostic.checks.lmstudio_reachable",
            detail_key="diagnostic.details.server_unreachable",
        ))
        return checks

    # Modèle conversation
    mdl_chat = (settings.get("lmstudio_model") or "").strip()
    if mdl_chat:
        checks.append(_chk(
            "Modèle conversation", OK, mdl_chat,
            name_key="diagnostic.checks.chat_model",
            detail_key="diagnostic.details.value",
            detail_vars={"value": mdl_chat},
        ))
    else:
        checks.append(_chk(
            "Modèle conversation", WARN, "Non configuré (réglage lmstudio_model vide)",
            name_key="diagnostic.checks.chat_model",
            detail_key="diagnostic.details.setting_empty",
            detail_vars={"setting": "lmstudio_model"},
        ))

    # Modèle utilitaire
    mdl_util = (settings.get("llm_util_model") or "").strip()
    if mdl_util:
        checks.append(_chk(
            "Modèle utilitaire", OK, mdl_util,
            name_key="diagnostic.checks.utility_model",
            detail_key="diagnostic.details.value",
            detail_vars={"value": mdl_util},
        ))
    else:
        checks.append(_chk(
            "Modèle utilitaire", WARN, "Non configuré — LLM conversation utilisé en fallback",
            name_key="diagnostic.checks.utility_model",
            detail_key="diagnostic.details.utility_fallback",
        ))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 3. ComfyUI
# ─────────────────────────────────────────────────────────────────────────────
def check_comfyui(settings, image_family="flux2_klein"):
    checks = []
    url = (settings.get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")
    checks.append(_chk(
        "URL ComfyUI", OK, url,
        name_key="diagnostic.checks.comfy_url",
        detail_key="diagnostic.details.value",
        detail_vars={"value": url},
    ))

    # Ping système
    try:
        data = _get_json(f"{url}/system_stats")
        ver = (data.get("system") or {}).get("comfyui_version", "?")
        checks.append(_chk(
            "ComfyUI joignable", OK, f"Version {ver}",
            name_key="diagnostic.checks.comfy_reachable",
            detail_key="diagnostic.details.version",
            detail_vars={"version": ver},
        ))
    except Exception as exc:
        checks.append(_chk(
            "ComfyUI joignable", ERR, "Serveur inaccessible", str(exc),
            name_key="diagnostic.checks.comfy_reachable",
            detail_key="diagnostic.details.server_unreachable",
        ))
        return checks

    # Queue
    try:
        queue = _get_json(f"{url}/queue")
        running = len(queue.get("queue_running", []))
        pending = len(queue.get("queue_pending", []))
        checks.append(_chk(
            "Queue ComfyUI", OK, f"En cours : {running}, en attente : {pending}",
            name_key="diagnostic.checks.comfy_queue",
            detail_key="diagnostic.details.queue_counts",
            detail_vars={"running": running, "pending": pending},
        ))
    except Exception as exc:
        checks.append(_chk(
            "Queue ComfyUI", WARN, "Impossible de lire la queue", str(exc),
            name_key="diagnostic.checks.comfy_queue",
            detail_key="diagnostic.details.queue_unreadable",
        ))

    # Critical nodes depend on the image engine selected in Diagnostic.
    if image_family == "krea2":
        nodes = [
            ("UNETLoader", "Node UNETLoader (Krea 2)", "diagnostic.checks.node_unet"),
            ("CLIPLoader", "Node CLIPLoader (Krea 2 text encoder)", "diagnostic.checks.node_clip_loader"),
            ("VAELoader", "Node VAELoader", "diagnostic.checks.node_vae_loader"),
            ("LoraLoader", "Node LoraLoader (Krea 2 slots)", "diagnostic.checks.node_lora_loader"),
            ("ResolutionSelector", "Node ResolutionSelector", "diagnostic.checks.node_resolution_selector"),
        ]
    else:
        nodes = [
            ("UnetLoaderGGUF", "Node UnetLoaderGGUF (GGUF)", "diagnostic.checks.node_gguf"),
            ("UNETLoader", "Node UNETLoader (Safetensors)", "diagnostic.checks.node_unet"),
            ("LoraLoaderModelOnly", "Node LoraLoaderModelOnly (LoRA slot)", "diagnostic.checks.node_lora_slot"),
        ]
    for node_type, label, name_key in nodes:
        try:
            data = _get_json(f"{url}/object_info/{node_type}", timeout=5)
            if node_type in data:
                checks.append(_chk(
                    label, OK, "Node disponible",
                    name_key=name_key,
                    detail_key="diagnostic.details.node_available",
                ))
                # Pour UNETLoader : lire weight_dtype
                if node_type == "UNETLoader":
                    try:
                        inputs = data["UNETLoader"].get("input", {}).get("required", {})
                        dt_info = inputs.get("weight_dtype", [])
                        allowed = dt_info[0] if isinstance(dt_info, list) and dt_info else []
                        default = dt_info[1].get("default", "") if len(dt_info) > 1 else ""
                        allowed_text = ", ".join(map(str, allowed))
                        checks.append(_chk(
                            "weight_dtype (UNETLoader)", OK,
                            f"Défaut : '{default}' — Valeurs : {allowed}",
                            name_key="diagnostic.checks.weight_dtype_unet",
                            detail_key="diagnostic.details.weight_dtype_values",
                            detail_vars={"default": default, "values": allowed_text},
                        ))
                    except Exception:
                        pass
            else:
                checks.append(_chk(
                    label, WARN, "Node non trouvé dans /object_info",
                    name_key=name_key,
                    detail_key="diagnostic.details.node_not_found",
                ))
        except Exception as exc:
            checks.append(_chk(
                label, WARN, "Impossible de vérifier ce node", str(exc),
                name_key=name_key,
                detail_key="diagnostic.details.node_uncheckable",
            ))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# 4. Flux 2 Klein
# ─────────────────────────────────────────────────────────────────────────────
def check_flux2_klein(settings, wf_dir):
    checks = []
    mode = (settings.get("flux2_loader_mode") or "gguf").strip()
    checks.append(_chk(
        "Mode actif", OK, f"flux2_loader_mode = {mode}",
        name_key="diagnostic.checks.active_mode",
        detail_key="diagnostic.details.mode_value",
        detail_vars={"mode": mode},
    ))

    if mode == "safetensors":
        # UNet Safetensors
        unet = (settings.get("img_unet_safetensors") or "").strip()
        if not unet:
            checks.append(_chk(
                "UNet Safetensors", ERR, "img_unet_safetensors vide",
                name_key="diagnostic.checks.unet_safetensors",
                detail_key="diagnostic.details.setting_empty",
                detail_vars={"setting": "img_unet_safetensors"},
            ))
        elif not unet.endswith(".safetensors"):
            checks.append(_chk(
                "UNet Safetensors", ERR,
                f"Extension invalide : {unet} (attendu .safetensors)",
                name_key="diagnostic.checks.unet_safetensors",
                detail_key="diagnostic.details.invalid_extension",
                detail_vars={"value": unet, "extension": ".safetensors"},
            ))
        else:
            checks.append(_chk(
                "UNet Safetensors", OK, unet,
                name_key="diagnostic.checks.unet_safetensors",
                detail_key="diagnostic.details.value",
                detail_vars={"value": unet},
            ))

        # weight_dtype
        weight_dtype = (settings.get("flux2_safetensors_weight_dtype") or "default").strip()
        fallback_value = "(vide — utilisera default)" if not weight_dtype else weight_dtype
        checks.append(_chk(
            "weight_dtype", OK if weight_dtype else WARN,
            f"Valeur configurée : '{fallback_value}'",
            name_key="diagnostic.checks.weight_dtype",
            detail_key="diagnostic.details.configured_value",
            detail_vars={"value": fallback_value},
        ))

        # Workflows _st.json
        for base in ["t2i", "i2i", "preview", "duo", "trio", "group4"]:
            checks.extend(_check_workflow(wf_dir, f"{base}_st.json", mode="safetensors"))

    else:  # gguf
        # UNet GGUF
        unet = (settings.get("img_unet_gguf") or settings.get("img_unet") or "").strip()
        if not unet:
            checks.append(_chk(
                "UNet GGUF", ERR, "img_unet_gguf vide",
                name_key="diagnostic.checks.unet_gguf",
                detail_key="diagnostic.details.setting_empty",
                detail_vars={"setting": "img_unet_gguf"},
            ))
        elif not unet.endswith(".gguf"):
            checks.append(_chk(
                "UNet GGUF", WARN, f"Extension inattendue : {unet}",
                name_key="diagnostic.checks.unet_gguf",
                detail_key="diagnostic.details.unexpected_extension",
                detail_vars={"value": unet},
            ))
        else:
            checks.append(_chk(
                "UNet GGUF", OK, unet,
                name_key="diagnostic.checks.unet_gguf",
                detail_key="diagnostic.details.value",
                detail_vars={"value": unet},
            ))

        # Workflows GGUF
        for base in ["t2i", "i2i", "preview", "duo", "trio", "group4"]:
            checks.extend(_check_workflow(wf_dir, f"{base}.json", mode="gguf"))

    # Composants communs CLIP + VAE
    for label, key, name_key in [
        ("CLIP", "img_clip", "diagnostic.checks.clip"),
        ("VAE", "img_vae", "diagnostic.checks.vae"),
    ]:
        value = (settings.get(key) or "").strip()
        checks.append(_chk(
            label, OK if value else WARN, value or f"{key} non configuré",
            name_key=name_key,
            detail_key="diagnostic.details.value" if value else "diagnostic.details.setting_not_configured",
            detail_vars={"value": value, "setting": key},
        ))

    return checks


def check_krea2(settings, wf_dir):
    """Validate the unified Krea 2 workflow and its configurable components."""
    checks = []
    workflow_rel = os.path.join("krea2", "krea2_unified.json")
    workflow_path = os.path.join(wf_dir, workflow_rel)

    components = [
        ("Krea 2 diffusion model", "diagnostic.checks.krea_diffusion", "krea2_unet", ".safetensors"),
        ("Krea 2 text encoder", "diagnostic.checks.krea_text_encoder", "krea2_clip", ".safetensors"),
        ("Krea 2 VAE", "diagnostic.checks.krea_vae", "krea2_vae", ".safetensors"),
    ]
    for label, name_key, key, extension in components:
        value = (settings.get(key) or "").strip()
        if not value:
            checks.append(_chk(label, ERR, f"{key} is empty", name_key=name_key,
                               detail_key="diagnostic.details.setting_empty", detail_vars={"setting": key}))
        elif extension and not value.lower().endswith(extension):
            checks.append(_chk(label, ERR, f"Invalid extension: {value}", name_key=name_key,
                               detail_key="diagnostic.details.invalid_extension",
                               detail_vars={"value": value, "extension": extension}))
        else:
            checks.append(_chk(label, OK, value, name_key=name_key,
                               detail_key="diagnostic.details.value", detail_vars={"value": value}))

    if not os.path.exists(workflow_path):
        checks.append(_chk("Krea 2 unified workflow", ERR, f"Missing: {workflow_rel}",
                           name_key="diagnostic.checks.krea_workflow",
                           detail_key="diagnostic.details.file_absent"))
        return checks
    try:
        with open(workflow_path, "r", encoding="utf-8") as handle:
            workflow = json.load(handle)
        node_types = [node.get("class_type") for node in workflow.values() if isinstance(node, dict)]
        required = ["UNETLoader", "CLIPLoader", "VAELoader", "KSampler",
                    "ResolutionSelector", "EmptyLatentImage", "SaveImage"]
        missing = [name for name in required if name not in node_types]
        lora_count = node_types.count("LoraLoader")
        if lora_count < 2:
            missing.append("2 × LoraLoader")
        if missing:
            missing_text = ", ".join(missing)
            checks.append(_chk("Krea 2 unified workflow", ERR,
                               "Missing node(s): " + missing_text,
                               technical=os.path.basename(workflow_path),
                               name_key="diagnostic.checks.krea_workflow",
                               detail_key="diagnostic.details.workflow_missing_nodes",
                               detail_vars={"nodes": missing_text}))
        else:
            checks.append(_chk("Krea 2 unified workflow", OK,
                               "Unified workflow valid, including ResolutionSelector and two LoRA slots",
                               technical=workflow_rel, name_key="diagnostic.checks.krea_workflow",
                               detail_key="diagnostic.details.krea_workflow_valid"))
    except Exception as exc:
        checks.append(_chk("Krea 2 unified workflow", ERR, "Invalid workflow JSON", str(exc),
                           name_key="diagnostic.checks.krea_workflow",
                           detail_key="diagnostic.details.invalid_json"))

    ratio = (settings.get("krea2_aspect_ratio") or "2:3 (Portrait Photo)").strip()
    mp = (settings.get("krea2_megapixels") or "2").strip()
    multiple = (settings.get("krea2_multiple") or "8").strip()
    try:
        mp_value = float(mp)
        mult_value = int(float(multiple))
        valid_resolution = mp_value > 0 and mult_value > 0
    except (TypeError, ValueError):
        valid_resolution = False
    resolution_detail = f"{ratio} · {mp} MP · multiple {multiple}"
    checks.append(_chk(
        "Krea 2 resolution", OK if valid_resolution else ERR,
        resolution_detail if valid_resolution else "Invalid Krea 2 resolution values",
        name_key="diagnostic.checks.krea_resolution",
        detail_key="diagnostic.details.value" if valid_resolution else "diagnostic.details.invalid_krea_resolution",
        detail_vars={"value": resolution_detail},
    ))

    for label, name_key, key in (
        ("Character LoRA", "diagnostic.checks.krea_character_lora", "krea2_char_lora"),
        ("Utility LoRA", "diagnostic.checks.krea_utility_lora", "krea2_util_lora"),
    ):
        value = (settings.get(key) or "").strip()
        checks.append(_chk(
            label, OK if value else SKIP, value or "Not selected", name_key=name_key,
            detail_key="diagnostic.details.value" if value else "diagnostic.details.not_selected",
            detail_vars={"value": value},
        ))
    return checks


def _check_workflow(wf_dir, filename, mode="gguf"):
    """Vérifie un fichier workflow JSON sans le modifier."""
    path = os.path.join(wf_dir, filename)
    name_args = {"filename": filename}

    if not os.path.exists(path):
        return [_chk(
            f"Workflow {filename}", ERR, "Fichier absent",
            name_key="diagnostic.checks.workflow", name_vars=name_args,
            detail_key="diagnostic.details.file_absent",
        )]

    try:
        with open(path, "r", encoding="utf-8") as handle:
            workflow = json.load(handle)
    except json.JSONDecodeError as exc:
        return [_chk(
            f"Workflow {filename}", ERR, "JSON invalide", str(exc),
            name_key="diagnostic.checks.workflow", name_vars=name_args,
            detail_key="diagnostic.details.invalid_json",
        )]
    except OSError as exc:
        return [_chk(
            f"Workflow {filename}", ERR, "Lecture impossible", str(exc),
            name_key="diagnostic.checks.workflow", name_vars=name_args,
            detail_key="diagnostic.details.file_unreadable",
        )]

    if not isinstance(workflow, dict) or not workflow:
        return [_chk(
            f"Workflow {filename}", ERR, "JSON vide ou non-dictionnaire",
            name_key="diagnostic.checks.workflow", name_vars=name_args,
            detail_key="diagnostic.details.empty_json",
        )]

    node_types = {node.get("class_type") for node in workflow.values() if isinstance(node, dict)}
    issues = []
    fallback_issues = []

    if mode == "safetensors":
        if "UNETLoader" not in node_types:
            issues.append({"key": "diagnostic.technical.workflow.unet_loader_missing"})
            fallback_issues.append("node UNETLoader absent")
        if "UnetLoaderGGUF" in node_types:
            issues.append({"key": "diagnostic.technical.workflow.gguf_loader_residual"})
            fallback_issues.append("node UnetLoaderGGUF résiduel (ne devrait pas être là)")
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "UNETLoader":
                inputs = node.get("inputs", {})
                if "weight_dtype" not in inputs:
                    issues.append({
                        "key": "diagnostic.technical.workflow.weight_dtype_missing",
                        "vars": {"node_id": node_id},
                    })
                    fallback_issues.append(f"input weight_dtype manquant dans node {node_id}")
                elif inputs.get("unet_name", "").endswith(".gguf"):
                    issues.append({
                        "key": "diagnostic.technical.workflow.unet_points_to_gguf",
                        "vars": {"node_id": node_id},
                    })
                    fallback_issues.append(f"unet_name pointe sur un .gguf dans node {node_id}")
    else:
        if "UnetLoaderGGUF" not in node_types:
            issues.append({"key": "diagnostic.technical.workflow.gguf_loader_missing"})
            fallback_issues.append("node UnetLoaderGGUF absent")

    for slot_id in ["301", "302"]:
        node = workflow.get(slot_id)
        if not node:
            issues.append({
                "key": "diagnostic.technical.workflow.lora_slot_missing",
                "vars": {"slot_id": slot_id},
            })
            fallback_issues.append(f"slot LoRA {slot_id} absent")
        elif node.get("class_type") not in ("LoraLoaderModelOnly", "LoraLoader"):
            class_type = node.get("class_type") or "?"
            issues.append({
                "key": "diagnostic.technical.workflow.lora_slot_invalid_class",
                "vars": {"slot_id": slot_id, "class_type": class_type},
            })
            fallback_issues.append(f"slot {slot_id} : class_type inattendu ({class_type})")

    if issues:
        return [_chk(
            f"Workflow {filename}", ERR, f"{len(issues)} problème(s) détecté(s)",
            " | ".join(fallback_issues),
            name_key="diagnostic.checks.workflow", name_vars=name_args,
            detail_key="diagnostic.details.problems_detected",
            detail_vars={"count": len(issues)},
            technical_items=issues,
        )]

    return [_chk(
        f"Workflow {filename}", OK, f"{len(workflow)} nodes, structure valide",
        name_key="diagnostic.checks.workflow", name_vars=name_args,
        detail_key="diagnostic.details.workflow_valid",
        detail_vars={"count": len(workflow)},
    )]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Bibliothèque / LoRA
# ─────────────────────────────────────────────────────────────────────────────
def check_library(db_path, data_dir, settings):
    del settings  # Gardé dans la signature pour la compatibilité avec run_all.
    checks = []
    civitai_cache = os.path.join(data_dir, "lora_previews", "civitai")

    # Dossiers surveillés
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        folders = conn.execute("SELECT * FROM model_folders").fetchall()
        conn.close()
        if folders:
            enabled = sum(1 for folder in folders if folder[3])
            checks.append(_chk(
                "Dossiers surveillés", OK, f"{len(folders)} dossier(s), {enabled} actif(s)",
                name_key="diagnostic.checks.watched_folders",
                detail_key="diagnostic.details.watched_folder_counts",
                detail_vars={"total": len(folders), "enabled": enabled},
            ))
            for row in folders:
                folder_path = row[1]
                exists = os.path.isdir(folder_path) if folder_path else False
                anon = _anon_path(folder_path)
                folder_name = os.path.basename(folder_path) or folder_path or "?"
                checks.append(_chk(
                    f"Dossier : {folder_name}", OK if exists else WARN,
                    anon if exists else f"Introuvable : {anon}",
                    name_key="diagnostic.checks.watched_folder",
                    name_vars={"name": folder_name},
                    detail_key="diagnostic.details.path_available" if exists else "diagnostic.details.path_missing",
                    detail_vars={"path": anon},
                ))
        else:
            checks.append(_chk(
                "Dossiers surveillés", WARN, "Aucun dossier configuré (Bibliothèque vide)",
                name_key="diagnostic.checks.watched_folders",
                detail_key="diagnostic.details.no_watched_folder",
            ))
    except Exception as exc:
        checks.append(_chk(
            "Dossiers surveillés", ERR, "Erreur lecture DB", str(exc),
            name_key="diagnostic.checks.watched_folders",
            detail_key="diagnostic.details.database_read_error",
        ))

    # Fichiers catalogués par kind
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        for kind in ["unet", "checkpoint", "vae", "clip", "lora", "controlnet"]:
            count = conn.execute(
                "SELECT COUNT(*) FROM model_files WHERE kind=? AND missing=0", (kind,)
            ).fetchone()[0]
            if count:
                checks.append(_chk(
                    f"Catalogue {kind}", OK, f"{count} fichier(s)",
                    name_key="diagnostic.checks.catalog_kind",
                    name_vars={"kind": kind},
                    detail_key="diagnostic.details.file_count",
                    detail_vars={"count": count},
                ))
            else:
                checks.append(_chk(
                    f"Catalogue {kind}", SKIP, "0 fichier indexé",
                    name_key="diagnostic.checks.catalog_kind",
                    name_vars={"kind": kind},
                    detail_key="diagnostic.details.zero_indexed_files",
                ))
        conn.close()
    except Exception as exc:
        checks.append(_chk(
            "Catalogue fichiers", ERR, "Erreur lecture", str(exc),
            name_key="diagnostic.checks.file_catalog",
            detail_key="diagnostic.details.database_read_error",
        ))

    # Cache Civitai
    if os.path.isdir(civitai_cache):
        count = len([filename for filename in os.listdir(civitai_cache)
                     if os.path.isfile(os.path.join(civitai_cache, filename))])
        checks.append(_chk(
            "Cache Civitai", OK, f"{count} preview(s) en cache",
            name_key="diagnostic.checks.civitai_cache",
            detail_key="diagnostic.details.cached_previews",
            detail_vars={"count": count},
        ))
    else:
        checks.append(_chk(
            "Cache Civitai", SKIP, "Dossier cache absent (normal si aucun scan Civitai)",
            name_key="diagnostic.checks.civitai_cache",
            detail_key="diagnostic.details.cache_folder_absent",
        ))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée principal
# ─────────────────────────────────────────────────────────────────────────────
def run_all(settings, db_path, data_dir, wf_dir, img_dir, image_family=None):
    """Lance tous les checks et retourne un rapport localisable côté client."""
    started = time.time()
    selected_family = (image_family or settings.get("image_family") or "flux2_klein").strip()
    if selected_family not in ("flux2_klein", "krea2"):
        selected_family = "flux2_klein"
    image_section = {
        "id": "krea2", "label": "Krea 2", "label_key": "diagnostic.sections.krea2",
        "checks": check_krea2(settings, wf_dir),
    } if selected_family == "krea2" else {
        "id": "flux2", "label": "Flux 2 Klein", "label_key": "diagnostic.sections.flux2",
        "checks": check_flux2_klein(settings, wf_dir),
    }
    sections = [
        {
            "id": "app", "label": "Application", "label_key": "diagnostic.sections.application",
            "checks": check_application(db_path, data_dir, wf_dir, img_dir),
        },
        {
            "id": "llm", "label": "LM Studio", "label_key": "diagnostic.sections.lmstudio",
            "checks": check_lmstudio(settings),
        },
        {
            "id": "comfy", "label": "ComfyUI", "label_key": "diagnostic.sections.comfyui",
            "checks": check_comfyui(settings, selected_family),
        },
        image_section,
        {
            "id": "library", "label": "Bibliothèque", "label_key": "diagnostic.sections.library",
            "checks": check_library(db_path, data_dir, settings),
        },
    ]
    elapsed = round(time.time() - started, 2)
    total_ok = sum(1 for section in sections for check in section["checks"] if check["status"] == OK)
    total_warn = sum(1 for section in sections for check in section["checks"] if check["status"] == WARN)
    total_err = sum(1 for section in sections for check in section["checks"] if check["status"] == ERR)
    return {
        "sections": sections,
        "elapsed": elapsed,
        "summary": {"ok": total_ok, "warning": total_warn, "error": total_err},
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "image_family": selected_family,
    }
