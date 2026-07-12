#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
AmiorAI local application server.

Run `python app.py`, then open http://127.0.0.1:8800.
Text generation is provided exclusively by LM Studio and image generation by ComfyUI.
User data is stored locally in the AmiorAI data folder.
"""

import json
import os
import sys

# Garantit que ce dossier (qui contient engine.py) est dans sys.path, quel que soit le
# mode de lancement. Sur une distribution Python "embeddable" (voir install.bat),
# sys.path est entierement dicte par le fichier ._pth et le dossier du script lance n'y est
# PAS ajoute automatiquement comme sur un Python standard -> sans cette ligne, "from engine
# import ..." echoue avec ModuleNotFoundError des qu'on lance via python_embed\python.exe.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

import model_manifests
import model_catalog
import diagnostic as diag_module
import llm_backends
import lmstudio_vram
import context_manager
import image_prompt_builder
import krea_prompt_builder

import base64
import hashlib
import logging
import math
import re
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------- #
#  Identite de l'application (marque)
#  Pour renommer l'appli, ne changer QUE cette constante : elle est utilisee
#  pour le titre de fenetre, le nom du dossier de donnees, les logs, etc.
#  Le code interne (DB, dossiers, variables) garde son nom technique d'origine
#  pour ne rien casser, mais rien de visible par l'utilisateur n'affiche plus
#  ce nom technique.
# --------------------------------------------------------------------------- #
# ─────────────────────────────────────────────────────────────────────────────
#  SESSIONS LAN — protection code d'accès réseau local (v33.1 hardened)
# ─────────────────────────────────────────────────────────────────────────────
import secrets as _secrets
import hashlib as _hashlib
import ipaddress as _ipaddress

# Sessions actives : {token: expiry_timestamp}
_lan_sessions: dict = {}
_LAN_SESSION_TTL = 86400 * 7   # 7 jours
_LAN_COOKIE_NAME = "amiorai_session"

# Rate limiting par IP : {ip: [timestamp_tentative, ...]}
_lan_fail_log: dict = {}
_LAN_MAX_TRIES   = 5      # essais max avant blocage
_LAN_WINDOW_SEC  = 600    # fenêtre de comptage (10 min)
_LAN_LOCKOUT_SEC = 900    # durée de blocage (15 min)

# Clés de réglages interdites sur GET /api/settings depuis LAN ou localhost
_SETTINGS_NEVER_EXPOSE = frozenset({
    "lan_access_code", "lan_access_code_hash",
    "civitai_token", "civitai_api_key",
    "openai_api_key", "anthropic_api_key",
    "llm_util_key", "lmstudio_api_key",
    "api_key", "password", "secret", "token",
})

# Réglages modifiables uniquement depuis localhost (admin-only)
_SETTINGS_ADMIN_ONLY = frozenset({
    "lan_mode", "lan_access_code", "lan_access_code_hash",
    "comfy_url", "lmstudio_url",
    "civitai_token",
})


# ── Hash du code LAN ─────────────────────────────────────────────────────────
def _lan_hash_code(code: str, salt: str = "") -> str:
    """Hash un code LAN via scrypt. Retourne 'salt:hash' encodé hex."""
    if not salt:
        salt = _secrets.token_hex(16)
    h = _hashlib.scrypt(
        code.encode(), salt=salt.encode(),
        n=16384, r=8, p=1, dklen=32
    )
    return f"{salt}:{h.hex()}"


def _lan_verify_code(code: str, stored: str) -> bool:
    """Vérifie un code contre son hash stocké 'salt:hex'."""
    try:
        salt, _ = stored.split(":", 1)
        expected = _lan_hash_code(code, salt)
        return _secrets.compare_digest(expected, stored)
    except Exception:
        return False


# ── Rate limiting ─────────────────────────────────────────────────────────────
def _lan_is_rate_limited(ip: str) -> bool:
    """Retourne True si l'IP doit être bloquée."""
    now = time.time()
    history = [t for t in _lan_fail_log.get(ip, []) if t > now - _LAN_WINDOW_SEC]
    _lan_fail_log[ip] = history
    return len(history) >= _LAN_MAX_TRIES and (now - history[0]) < _LAN_LOCKOUT_SEC


def _lan_record_fail(ip: str):
    """Enregistre un échec de connexion pour l'IP (jamais pour localhost)."""
    if _lan_is_local(ip):
        return
    now = time.time()
    _lan_fail_log.setdefault(ip, []).append(now)


def _lan_clear_fail(ip: str):
    """Efface les tentatives après succès."""
    _lan_fail_log.pop(ip, None)


# ── Sessions ──────────────────────────────────────────────────────────────────
def _lan_new_session() -> str:
    """Crée un token de session sécurisé (64 chars hex)."""
    token = _secrets.token_hex(32)
    _lan_sessions[token] = time.time() + _LAN_SESSION_TTL
    return token


def _lan_revoke_all_sessions():
    """Invalide toutes les sessions LAN en cours."""
    _lan_sessions.clear()


def _lan_count_sessions() -> int:
    now = time.time()
    return sum(1 for exp in _lan_sessions.values() if exp > now)


def _lan_check_session(cookie_header: str) -> bool:
    """Valide un token de session depuis le header Cookie."""
    if not cookie_header:
        return False
    now = time.time()
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(_LAN_COOKIE_NAME + "="):
            token = part[len(_LAN_COOKIE_NAME) + 1:].split()[0]
            if token in _lan_sessions and _lan_sessions[token] > now:
                return True
    return False


def _lan_is_local(client_addr: str) -> bool:
    """Retourne True si la requête vient du PC lui-même."""
    return (client_addr or "").split(":")[0] in ("127.0.0.1", "::1", "localhost")


def _lan_session_cookie(token: str) -> str:
    # SameSite=Lax (pas Strict) pour permettre la redirection POST → GET
    return (f"{_LAN_COOKIE_NAME}={token}; HttpOnly; SameSite=Lax; "
            f"Path=/; Max-Age={_LAN_SESSION_TTL}")


# ── Détection IP locale sans DNS externe ─────────────────────────────────────
def _lan_get_local_ip() -> str:
    """Retourne l'IP LAN privée du PC sans appel DNS externe.
    Préfère 192.168.x.x > 10.x.x.x > 172.16-31.x.x."""
    import socket as _socket
    candidates = []
    try:
        hostname = _socket.gethostname()
        infos = _socket.getaddrinfo(hostname, None, _socket.AF_INET)
        for info in infos:
            ip = info[4][0]
            try:
                addr = _ipaddress.IPv4Address(ip)
                if addr.is_private and not addr.is_loopback and not addr.is_link_local:
                    candidates.append(ip)
            except Exception:
                pass
    except Exception:
        pass
    # Fallback : UDP trick sans envoi réel
    if not candidates:
        try:
            import socket as _s
            with _s.socket(_s.AF_INET, _s.SOCK_DGRAM) as s:
                s.settimeout(0)
                s.connect(("192.168.1.1", 1))
                candidates.append(s.getsockname()[0])
        except Exception:
            pass
    # Trier par préférence : 192.168 > 10 > 172.16-31
    def _pref(ip):
        if ip.startswith("192.168."): return 0
        if ip.startswith("10."):      return 1
        return 2
    candidates.sort(key=_pref)
    return candidates[0] if candidates else "?.?.?.?"


# ── Filtrage des réglages exposés ─────────────────────────────────────────────
def _get_safe_settings(is_local: bool = True) -> dict:
    """Retourne les réglages filtrés pour le frontend.
    Remplace les valeurs sensibles par des indicateurs booléens."""
    s = get_settings()
    out = {k: v for k, v in s.items() if k not in _SETTINGS_NEVER_EXPOSE}
    # Indicateurs de présence (sans la valeur réelle)
    out["lan_code_set"]         = bool(s.get("lan_access_code_hash"))
    out["civitai_token_set"]    = bool(s.get("civitai_token"))
    out["llm_util_key_set"]     = bool(s.get("llm_util_key"))
    out["lmstudio_api_key_set"] = bool(s.get("lmstudio_api_key"))
    out["lan_mode"]             = s.get("lan_mode", "local")
    out["lan_enabled"]          = s.get("lan_mode", "local") == "lan"
    # Depuis un client LAN : masquer aussi les réglages admin-only
    if not is_local:
        for k in _SETTINGS_ADMIN_ONLY:
            out.pop(k, None)
    return out


# ── Vérification sécurité démarrage LAN ──────────────────────────────────────
def _lan_startup_safe(settings: dict) -> tuple:
    """Retourne (bind_host, safe) — force 127.0.0.1 si LAN sans hash valide."""
    mode = settings.get("lan_mode", "local")
    if mode != "lan":
        return "127.0.0.1", True
    has_hash = bool(settings.get("lan_access_code_hash", "").strip())
    if not has_hash:
        log.warning("[LAN] LAN mode enabled but no hashed code is configured → "
                    "forced bind to 127.0.0.1")
        return "127.0.0.1", False
    return "0.0.0.0", True


# ─────────────────────────────────────────────────────────────────────────────
#  CAPACITÉS LAN — routes autorisées / bloquées depuis un client réseau local
# ─────────────────────────────────────────────────────────────────────────────

# Routes GET accessibles depuis un client LAN authentifié
_LAN_ALLOWED_GET = frozenset({
    "/", "/mobile", "/lan_login",
    "/favicon.ico",
    "/api/client-context",
    "/api/health",
    "/api/settings",
    "/api/characters", "/api/character",
    "/api/chats", "/api/chat",
    "/api/gallery",
    "/api/memory", "/api/char_memory", "/api/char_mood", "/api/char_emotions",
    "/api/scenarios", "/api/journal",
    "/api/image/families", "/api/image/compatibility",
    "/api/loras", "/api/lora/presets", "/api/lora/workflow_compat",
    "/api/lora/preview", "/api/lora/previews", "/api/chat/lora",
    "/api/llm/status", "/api/runtime/status", "/api/tts/status",
    "/api/config/previews",
})

# Préfixes GET autorisés depuis LAN (path.startswith)
_LAN_ALLOWED_GET_PREFIXES = (
    "/lora_preview/", "/img/", "/images/", "/audio/", "/static/",
    "/web/", "/logo",
)

# Routes POST accessibles depuis un client LAN authentifié
_LAN_ALLOWED_POST = frozenset({
    "/lan_login",
    "/api/lan/logout",
    # Messages / conversations
    "/api/message/send", "/api/message/continue", "/api/message/react",
    "/api/message/speak",
    "/api/chat/create", "/api/chat/reset", "/api/chat/group/add",
    "/api/chat/lora",
    # Personnages
    "/api/character/save", "/api/character/select", "/api/character/avatar",
    # Image
    "/api/image/generate",
    # Galerie
    "/api/gallery/delete",
    # Audio
    "/api/dictate",
    "/api/tts/speak", "/api/tts/start",
    # Mémoire
    "/api/memory/save",
})

# Réponse standard pour les routes host-only
def _lan_host_only_response(handler):
    data = json.dumps({
        "error": "host_only",
        "message": "This action must be performed from the host PC."
    }).encode()
    handler.send_response(403)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _lan_route_allowed(method: str, path: str) -> bool:
    """Retourne True si la route est accessible depuis un client LAN."""
    # Retirer les query strings
    clean = path.split("?")[0].rstrip("/") or "/"
    if method == "GET":
        if clean in _LAN_ALLOWED_GET:
            return True
        return any(clean.startswith(p) for p in _LAN_ALLOWED_GET_PREFIXES)
    if method == "POST":
        return clean in _LAN_ALLOWED_POST
    return False


_LAN_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AmiorAI — LAN access</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0d0a14;color:#e0d0f0;
    display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
  .box{background:#1a1225;border:1px solid #3a2850;border-radius:16px;padding:36px 40px;
    max-width:360px;width:100%;text-align:center;}
  h1{font-size:1.3rem;margin:0 0 8px;}
  .sub{color:#8070a0;font-size:13px;margin-bottom:24px;}
  input{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:8px;
    border:1px solid #3a2850;background:#0d0a14;color:#e0d0f0;font-size:16px;
    text-align:center;letter-spacing:4px;margin-bottom:14px;}
  button{width:100%;padding:12px;border-radius:8px;border:none;
    background:#7c3aed;color:#fff;font-size:15px;font-weight:600;cursor:pointer;}
  button:hover{background:#6d28d9;}
  .err{color:#ef4444;font-size:13px;margin-top:10px;}
  .note{color:#6050a0;font-size:11px;margin-top:20px;line-height:1.6;}
</style></head><body>
<div class="box">
  <h1>AmiorAI</h1>
  <p class="sub">LAN access — entrez le code d'accès</p>
  <form method="POST" action="/lan_login">
    <input type="password" name="code" placeholder="Code d'accès" autocomplete="off" autofocus>
    <button type="submit">Accéder</button>
    {error}
  </form>
  <p class="note">Le code se trouve dans AmiorAI → Réglages → Réseau local<br>
  Accessible uniquement sur votre réseau local privé.</p>
</div></body></html>"""


APP_NAME = "AmiorAI"
APP_VERSION = "v40.0.7"

# --------------------------------------------------------------------------- #
#  Chemins et constantes — source unique : app_paths.py
#  (importé aussi par engine.py — plus aucune duplication possible)
# --------------------------------------------------------------------------- #
from app_paths import (  # noqa: E402
    CODE_ROOT, DATA_ROOT, WEB_DIR, WF_DIR,
    DATA_DIR, IMG_DIR, LOG_DIR, BACKUP_DIR, DB_PATH,
    LEGACY_IMG_DIR, resolve_img,
)
ROOT = CODE_ROOT  # alias historique

# --------------------------------------------------------------------------- #
#  Journalisation fichier (en plus de la console) : indispensable en .exe ou
#  aucune console n'est forcement visible. Fichier exploitable, taille bornee.
# --------------------------------------------------------------------------- #
_log_path = os.path.join(LOG_DIR, "app.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(APP_NAME)

HOST = "127.0.0.1"  # Redéfini au démarrage selon le réglage lan_mode
PORT = 8800

# Reglages par defaut (modifiables ensuite dans l'onglet Reglages)
DEFAULT_SETTINGS = {
    # ---- LLM ----
    "llm_backend": "lmstudio",                  # LM Studio is the only supported LLM backend
    "llm_ctx": "8192",                           # taille de contexte
    "llm_temperature": "0.85",
    "llm_max_tokens": "250",                      # longueur des réponses conversationles (slider dans le chat)
    # ---- LoRA (injectes dans les workflows image) ----
    "loras": "[]",                                # JSON: [{file, trigger, strength, always}]
    # ---- Overrides prompts avancés (vides = prompt officiel intégré utilisé) ----
    "override_chargen_system":        "",         # override CHARGEN_SYSTEM (création personnage)
    "override_scene_planner_prompt":  "",         # override SCENE_PLANNER_SYSTEM_PROMPT Flux
    "override_krea_scene_planner_prompt": "",     # override Krea 2 scene planner prompt
    "override_conversation_style_prompt": "",     # override roleplay conversation style prompt
    # ---- Modele utility (optionnel) pour taches structurees (creation perso, prompts image, scenarios) ----
    # Optional utility model hosted by the same LM Studio server.
    "llm_util_enabled": "false",                  # true = utilise un 2e modele pour les taches structurees
    "llm_util_backend": "lmstudio",              # utility model uses the same LM Studio server
    "llm_util_url": "http://127.0.0.1:1234/v1",  # compatibility mirror of lmstudio_url
    "llm_util_model": "",                       # exact LM Studio model ID; empty = main model
    "llm_util_key": "",                           # cle API optionnelle pour le serveur utility
    "llm_util_fallback": "false",                 # true = autorise le repli explicite vers le LLM
                                                   # conversation si l'utility est indisponible
                                                   # (desactive par defaut : echec clair plutot que silencieux)
    # ---- Voix : TTS local (Chatterbox V3 par defaut, Qwen3-TTS optionnel) ----
    "tts_enabled": "false",                       # active la synthese vocale
    "tts_path": "",                                # dossier tts_server/ (vide = celui livre avec l'appli)
    "tts_url": "http://127.0.0.1:8810",
    "tts_autolaunch": "true",
    "tts_engine": "chatterbox",                   # chatterbox / qwen
    "tts_device": "auto",                         # auto / cuda / cpu
    "tts_vram_offload_enabled": "true",           # stoppe le TTS CUDA avant LM Studio/ComfyUI et inversement
    "tts_start_timeout": "900",                   # premier telechargement du modele parfois long
    "tts_language": "en",
    "tts_speed": "1.0",
    "tts_exaggeration": "0.5",                    # Chatterbox : expressivite
    "tts_cfg_weight": "0.5",                      # Chatterbox : fidelite / rythme
    "tts_temperature": "0.8",                     # Chatterbox : variation
    "tts_qwen_model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "tts_autoplay": "true",                       # joue automatiquement l'audio des reponses
    # ---- Voix : Whisper local (dictee, 100% hors-ligne) ----
    "whisper_enabled": "false",
    "whisper_model_size": "small",                  # tiny / base / small / medium / large-v3
    "whisper_device": "auto",
    "whisper_language": "",                         # vide = detection auto
    # ---- Image (ComfyUI tiers, connexion API uniquement) ----
    "comfy_url": "http://127.0.0.1:8188",        # adresse de l'instance ComfyUI lancee separement
    "t2i_workflow": "t2i.json",
    "i2i_workflow": "i2i.json",
    "duo_workflow": "duo.json",
    "trio_workflow": "trio.json",
    "group_workflow": "group4.json",
    "preview_workflow": "preview.json",
    "prompt_token": "%PROMPT%",
    "negative_token": "%NEGATIVE%",
    "image_token": "%IMAGE%",
    "default_negative": "",
    # ---- Resolution de generation ----
    "image_resolution": "1024x1024",   # Carré 1:1 par défaut
    # ---- Modèles image (noms de fichiers dans ton ComfyUI) ----
    # Ces 4 cles restent la source de verite pour la famille flux2_klein (compat totale avec
    # l'existant). Les autres familles ont leurs propres cles, voir model_manifests.FAMILIES.
    "img_unet": "",                            # héritage — lu si img_unet_gguf absent
    "img_unet_gguf":          "",                            # UNet GGUF Flux 2 Klein — à sélectionner dans Studio Image
    "img_unet_safetensors":   "",                              # UNet Safetensors Flux 2 Klein
    "flux2_loader_mode":      "gguf",                          # "gguf" | "safetensors"
    "flux2_safetensors_weight_dtype": "default",
    # ---- Réseau local ----
    "lan_mode":        "local",  # "local" = 127.0.0.1 | "lan" = 0.0.0.0
    "lan_access_code": "",       # Code PIN LAN (généré à la demande)               # weight_dtype pour UNETLoader (valeur /object_info/UNETLoader)
    "img_clip": "",            # CLIP / Text Encoder — à sélectionner dans Studio Image ou Réglages
    "img_clip_type": "flux2",
    "img_vae": "",              # VAE — à sélectionner dans Studio Image ou Réglages
    # ---- Famille de workflow active (Studio Image) ----
    "image_family": "flux2_klein",                # global image engine: flux2_klein or krea2
    "image_show_incompatible": "false",            # afficher aussi les modeles a famille incertaine/differente
    # ---- Composants par famille (vides par defaut, l'utilisateur les choisit dans Studio Image) ----
    "sd15_checkpoint": "", "sd15_vae": "", "sd15_loras": "[]",
    "sdxl_checkpoint": "", "sdxl_vae": "", "sdxl_loras": "[]",
    "flux_unet": "", "flux_clip": "", "flux_vae": "", "flux_loras": "[]",
    "zimage_unet": "", "zimage_vae": "",
    # ---- Krea 2 (workflow unifié unique) ----
    # Modèles par défaut : ceux du workflow de référence fourni (adaptables dans Studio).
    "krea2_unet": "krea2_turbo_fp8_scaled.safetensors",   # modèle de diffusion (Turbo/Raw/...)
    "krea2_clip": "qwen3vl_4b_fp8_scaled.safetensors",    # encodeur texte (type krea2)
    "krea2_vae":  "qwen_image_vae.safetensors",
    "krea2_char_lora": "",                # LoRA personnage principal — slot 301, optionnel
    "krea2_char_lora_strength": "1.0",    # force du LoRA personnage principal
    "krea2_char2_lora": "",               # LoRA personnage secondaire / user persona — slot 302, optionnel
    "krea2_char2_lora_strength": "1.0",   # force du LoRA personnage secondaire
    "krea2_user_token": "",               # trigger optionnel du LoRA user/persona dans le prompt
    "krea2_util_lora": "",                # LoRA utilitaire (style/rendu) — slot 303, optionnel
    "krea2_util_lora_strength": "0.8",    # force du LoRA utilitaire
    "krea2_steps": "8",                   # steps sampler (8 = Krea 2 Turbo)
    "krea2_cfg": "1.0",                   # cfg sampler (1.0 = Krea 2 Turbo)
    "krea2_preview_steps": "6",           # reduced steps for previews (templates, LoRA)
    "krea2_sampler_profile": "auto",        # auto | turbo | raw | custom
    "krea2_aspect_ratio": "2:3 (Portrait Photo)",
    "krea2_megapixels": "2",
    "krea2_multiple": "8",
    "wan_model": "", "wan_clip": "", "wan_vae": "",
    "ltx_model": "", "ltx_clip": "", "ltx_vae": "",
    # ---- Backend LLM additionnel : LM Studio ----
    "lmstudio_url": "http://127.0.0.1:1234/v1",   # adresse du serveur local LM Studio
    "lmstudio_model": "",                          # identifiant du modele tel qu'expose par LM Studio
    "lmstudio_api_key": "",                        # cle API optionnelle, utilisee seulement si LM Studio l'exige
    "lmstudio_vram_offload_enabled": "true",       # decharge les modeles AmiorAI de LM Studio avant une generation image
    "lmstudio_reload_on_demand": "true",           # recharge automatiquement le modele requis a la prochaine requete texte
    "lmstudio_unload_conversation_before_utility": "true",  # decharge le conversation avant une tache utility (GPU exclusif)
    "lmstudio_unload_utility_after_use": "true",            # decharge l'utility immediatement apres chaque tache (GPU exclusif)
    "lmstudio_native_timeout": "240",              # timeout appels natifs LM Studio load/unload/models (s)
    "lmstudio_request_timeout": "600",             # timeout generation texte via API OpenAI-compatible (s)
    "lmstudio_load_wait_timeout": "180",           # attente max confirmation modele charge (s)
    "lmstudio_post_load_delay": "4",               # pause de stabilisation apres chargement modele (s)
    "lmstudio_post_unload_delay": "1.5",           # pause de stabilisation apres dechargement modele (s)
    "lmstudio_retry_after_load_error": "true",     # relance une requete texte LM Studio apres erreur transitoire
    "comfy_vram_offload_before_lmstudio": "true",  # release ComfyUI before an LM Studio reload
    "comfy_vram_release_timeout": "30",            # seconds to confirm ComfyUI VRAM release
    "comfy_busy_wait_timeout": "180",              # seconds to wait for an active ComfyUI generation
    # ---- Contexte conversation dynamique (resume roulant) ----
    "context_compaction_enabled": "true",          # active la construction de contexte budgetee + resume roulant
    "context_distribution_mode": "auto",           # "auto" = calcule memoire/resume/messages depuis llm_ctx+llm_max_tokens (v10).
                                                    # toute autre valeur = mode legacy, utilise les 4 cles ci-dessous telles quelles.
    "context_input_target_tokens": "3500",         # LEGACY (mode auto ignore cette cle) : ancien plafond fixe
    "context_recent_messages": "8",                # LEGACY (mode auto ignore cette cle) : ancien nb fixe de messages recents
    "context_compaction_min_new_messages": "4",    # nb min de nouveaux messages avant de declencher une consolidation
    "context_compaction_idle_seconds": "20",       # delai d'inactivite avant de lancer la consolidation differee
    "context_summary_max_tokens": "900",           # LEGACY (mode auto ignore cette cle) : ancienne taille fixe du resume
    "context_memory_max_tokens": "700",            # LEGACY (mode auto ignore cette cle) : ancien budget memoire fixe
    # ---- Persona (le joueur) ----
    "persona_name": "",                          # ton nom dans le jeu de role
    "persona_description": "",                   # qui tu es (injecte dans le prompt systeme)
    "persona_image": "",                         # ton image (fichier dans data/images) - reference possible
    "persona_in_images": "false",                # inclure ta persona comme reference dans les scenes de groupe
    # ---- Gestion VRAM ----
    "vram_mode": "swap",                          # swap = libere le LLM pendant l'image et inversement (<=16 Go)
    # ---- Langue de l'interface (i18n) ----
    "ui_language": "en",                          # fr / en / es / de — interface language and LLM prompt language
}
# Obsolete since v40.0.7: AmiorAI no longer manages a ComfyUI process.
_OBSOLETE_COMFY_PROCESS_SETTINGS = frozenset({
    "comfy_path", "comfy_python", "comfy_autolaunch",
    "comfy_extra_args", "comfy_start_timeout",
})


# --------------------------------------------------------------------------- #
#  Base de donnees
# --------------------------------------------------------------------------- #
_db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _backup_db():
    """Sauvegarde atomique de companion.db via SQLite backup API.
    Conserve les 5 dernières sauvegardes, ne jamais écraser une existante."""
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        return None
    import datetime
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"companion_{stamp}.db")
    if os.path.exists(dst):
        return dst  # éviter l'écrasement
    try:
        import sqlite3 as _sq
        src_conn = _sq.connect(DB_PATH)
        dst_conn = _sq.connect(dst)
        src_conn.backup(dst_conn)
        src_conn.close()
        dst_conn.close()
        log.info(f"[DB] Backup created: {dst}")
        # Conserver seulement les 5 dernières
        backups = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.startswith("companion_") and f.endswith(".db")],
            reverse=True
        )
        for old_bk in backups[5:]:
            try: os.remove(os.path.join(BACKUP_DIR, old_bk))
            except Exception: pass
        return dst
    except Exception as e:
        log.warning(f"[DB] Unable to create backup: {e}")
        return None


def _check_db_integrity():
    """Vérifie que companion.db n'est pas un fichier vide (archive de build).
    Si 0 octet ET dossier data semble neuf → continuer normalement.
    Si 0 octet ET présence d'autres fichiers data → warning fort."""
    if not os.path.exists(DB_PATH):
        return  # première installation, normal
    size = os.path.getsize(DB_PATH)
    if size == 0:
        # Chercher des indices que des données existaient (images, audio...)
        has_images = any(os.listdir(IMG_DIR)) if os.path.isdir(IMG_DIR) else False
        if has_images:
            log.error("[DB] WARNING: companion.db is empty (0 bytes) but images exist "
                      "in data/images/. The database may have been overwritten by a "
                      "build archive. Check your installation and restore a backup.")
        else:
            log.warning("[DB] Empty companion.db detected — first install or reset database.")
        # Dans tous les cas : supprimer le fichier vide pour que CREATE TABLE IF NOT EXISTS
        # crée une vraie base propre (pas de corruption silencieuse)
        os.remove(DB_PATH)
        log.info("[DB] Empty file removed — a clean new database will be created.")


def init_db():
    _check_db_integrity()
    # Sauvegarde avant toute migration si la base existe déjà avec des données
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
        try:
            import sqlite3 as _sq
            conn = _sq.connect(DB_PATH)
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            conn.close()
            # Ne sauvegarder que si la base a déjà des tables utilisateur (pas une base neuve)
            if "characters" in tables or "chats" in tables:
                _backup_db()
        except Exception as e:
            log.warning(f"[DB] Pre-migration check: {e}")
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS characters (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                age           TEXT,
                personality   TEXT,
                appearance    TEXT,
                scenario      TEXT,
                greeting      TEXT,
                system_prompt TEXT,
                image_prompt  TEXT,
                avatar        TEXT,
                created_at    REAL
            );
            CREATE TABLE IF NOT EXISTS chats (
                id         TEXT PRIMARY KEY,
                title      TEXT,
                is_group   INTEGER DEFAULT 0,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS chat_members (
                chat_id      TEXT,
                character_id TEXT,
                PRIMARY KEY (chat_id, character_id),
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS messages (
                id           TEXT PRIMARY KEY,
                chat_id      TEXT,
                role         TEXT,          -- 'user' ou 'assistant'
                character_id TEXT,          -- qui parle (null si user)
                content      TEXT,
                image        TEXT,          -- nom de fichier image eventuel
                created_at   REAL,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS gallery (
                id           TEXT PRIMARY KEY,
                character_id TEXT,
                image        TEXT,
                prompt       TEXT,
                seed         INTEGER,
                created_at   REAL
            );
            CREATE TABLE IF NOT EXISTS memory (
                id           TEXT PRIMARY KEY,
                character_id TEXT,
                kind         TEXT,          -- 'short' ou 'long'
                content      TEXT,
                created_at   REAL,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS option_previews (
                field      TEXT,
                value      TEXT,
                gender     TEXT,
                family     TEXT DEFAULT 'flux2_klein',
                image      TEXT,
                created_at REAL,
                PRIMARY KEY (field, value, gender, family)
            );
            CREATE TABLE IF NOT EXISTS char_memory (
                id           TEXT PRIMARY KEY,
                character_id TEXT NOT NULL,
                likes        TEXT,
                dislikes     TEXT,
                important_events TEXT,
                user_preferences TEXT,
                relationship_history TEXT,
                last_topic   TEXT,
                last_image   TEXT,
                current_relationship_state TEXT,
                updated_at   REAL,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS char_mood (
                character_id  TEXT PRIMARY KEY,
                affection     INTEGER DEFAULT 50,
                trust         INTEGER DEFAULT 50,
                energy        INTEGER DEFAULT 70,
                curiosity     INTEGER DEFAULT 60,
                stress        INTEGER DEFAULT 10,
                mood          TEXT DEFAULT 'neutral',
                mood_since    INTEGER DEFAULT 0,
                last_msg_id   TEXT DEFAULT '',
                updated_at    REAL,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS char_emotions (
                character_id TEXT,
                emotion      TEXT,       -- happy / calm / playful / shy / sad / angry / tired / excited / romantic / cold
                image        TEXT,       -- nom de fichier dans data/images/
                created_at   REAL,
                PRIMARY KEY (character_id, emotion)
            );
            CREATE TABLE IF NOT EXISTS scenarios (
                id           TEXT PRIMARY KEY,
                title        TEXT,
                place        TEXT,
                mood_theme   TEXT,
                theme        TEXT,
                relationship TEXT,
                goal         TEXT,
                conflict     TEXT,
                notes        TEXT,
                created_at   REAL
            );
            CREATE TABLE IF NOT EXISTS journal (
                id           TEXT PRIMARY KEY,
                character_id TEXT,           -- null = global
                kind         TEXT,           -- moment / first_meeting / favorite / saved_image / memory_event
                title        TEXT,
                content      TEXT,
                image        TEXT,           -- image associee eventuelle
                date         TEXT,           -- 'YYYY-MM-DD'
                created_at   REAL,
                pinned       INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS loras (
                id          TEXT PRIMARY KEY,
                file        TEXT,
                trigger     TEXT,
                strength    REAL DEFAULT 0.8,
                always_on   INTEGER DEFAULT 0,
                note        TEXT,
                created_at  REAL
            );
            CREATE TABLE IF NOT EXISTS lora_presets (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                family      TEXT,
                context     TEXT,
                context_id  TEXT,
                stack       TEXT,
                created_at  REAL
            );
            CREATE TABLE IF NOT EXISTS chat_lora_selection (
                chat_id              TEXT PRIMARY KEY,
                primary_lora_file    TEXT,
                primary_strength     REAL DEFAULT 0.8,
                primary_clip_str     REAL DEFAULT 1.0,
                secondary_lora_file  TEXT,
                secondary_strength   REAL DEFAULT 0.8,
                secondary_clip_str   REAL DEFAULT 1.0,
                apply_once           INTEGER DEFAULT 0,
                updated_at           REAL,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS lora_previews (
                lora_name    TEXT PRIMARY KEY,
                family       TEXT,
                preview_path TEXT,
                preview_source TEXT,       -- 'generated' | 'selected_gallery' | 'imported_file'
                prompt_used  TEXT,
                workflow_used TEXT,
                seed         INTEGER,
                updated_at   REAL
            );
            CREATE TABLE IF NOT EXISTS lora_civitai_metadata (
                model_file_id            TEXT PRIMARY KEY,
                file_hash                TEXT,
                hash_type                TEXT DEFAULT 'SHA256',
                cached_size              INTEGER,
                cached_mtime             REAL,
                civitai_model_id         INTEGER,
                civitai_model_version_id INTEGER,
                civitai_model_name       TEXT,
                civitai_version_name     TEXT,
                civitai_creator          TEXT,
                civitai_base_model       TEXT,
                civitai_url              TEXT,
                civitai_tags_json        TEXT,
                civitai_trigger_words_json TEXT,
                civitai_preview_url      TEXT,
                civitai_preview_path     TEXT,
                civitai_last_sync        REAL,
                civitai_match_status     TEXT,
                civitai_last_error       TEXT,
                -- Identification manuelle / priorité (v21)
                detected_file_type       TEXT,   -- type détecté automatiquement
                detected_family          TEXT,   -- famille détectée automatiquement
                manual_file_type         TEXT,   -- override manuel type
                manual_family            TEXT,   -- override manuel famille
                identification_source    TEXT DEFAULT 'auto',  -- 'auto' | 'civitai' | 'manual'
                civitai_manual_url       TEXT,   -- URL collée manuellement
                civitai_association_confirmed INTEGER DEFAULT 0,  -- 1 si confirmé par l'utilisateur
                updated_at               REAL
            );
            """
        )
        # migrations non-destructives pour la table loras (v14)
        _add_col(c, "loras", "family",        "TEXT")
        _add_col(c, "loras", "clip_strength",  "REAL DEFAULT 1.0")
        _add_col(c, "loras", "favorite",       "INTEGER DEFAULT 0")
        _add_col(c, "characters", "locked_tags", "TEXT")
        _add_col(c, "characters", "last_seed", "INTEGER")
        _add_col(c, "characters", "role", "TEXT")
        _add_col(c, "characters", "moral_limits", "TEXT")
        _add_col(c, "characters", "voice_sample", "TEXT")  # nom de fichier audio dans data/voices/
        _add_col(c, "characters", "voice_transcript", "TEXT")  # transcription exacte, optionnelle pour Qwen3-TTS
        # migrations Krea 2 (v38.1) — identité et base physique persistante
        _add_col(c, "characters", "krea_token", "TEXT")                       # jeton d'identité (trigger LoRA) pour les prompts Krea 2
        _add_col(c, "characters", "krea_force_physical", "INTEGER DEFAULT 1")  # 1 = injecter la base physique du configurateur dans chaque prompt Krea 2
        _add_col(c, "chats", "scenario_id", "TEXT")
        _add_col(c, "messages", "image_prompt", "TEXT")
        _add_col(c, "messages", "seed", "INTEGER")
        _add_col(c, "messages", "audio", "TEXT")
        _add_col(c, "chat_members", "active", "INTEGER DEFAULT 1")
        _add_col(c, "gallery", "seed", "INTEGER")
        _add_col(c, "gallery", "source", "TEXT")
        # migrations lora_civitai_metadata (v20) — colonnes ajoutées progressivement
        _add_col(c, "lora_civitai_metadata", "civitai_last_error", "TEXT")
        _add_col(c, "lora_civitai_metadata", "hash_type",          "TEXT")
        # migrations lora_civitai_metadata (v21) — identification manuelle
        _add_col(c, "lora_civitai_metadata", "detected_file_type",            "TEXT")
        _add_col(c, "lora_civitai_metadata", "detected_family",               "TEXT")
        _add_col(c, "lora_civitai_metadata", "manual_file_type",              "TEXT")
        _add_col(c, "lora_civitai_metadata", "manual_family",                 "TEXT")
        _add_col(c, "lora_civitai_metadata", "identification_source",         "TEXT DEFAULT 'auto'")
        _add_col(c, "lora_civitai_metadata", "civitai_manual_url",            "TEXT")
        _add_col(c, "lora_civitai_metadata", "civitai_association_confirmed", "INTEGER DEFAULT 0")
        _add_col(c, "lora_civitai_metadata", "updated_at",                    "REAL")
        # migration : supprimer l'ancienne colonne current_mood de char_memory si elle existe
        # (SQLite ne supporte pas DROP COLUMN avant 3.35 — on la laisse, elle sera ignoree)
        # Migration option_previews: v38.1.1 adds the image family to the cache key.
        # Existing previews are from the historical Flux pipeline, so they are preserved as flux2_klein.
        opinfo = c.execute("PRAGMA table_info(option_previews)").fetchall()
        opcols = [r[1] for r in opinfo]
        if opcols and ("gender" not in opcols or "family" not in opcols):
            c.execute("ALTER TABLE option_previews RENAME TO option_previews_legacy")
            c.execute(
                "CREATE TABLE option_previews ("
                "field TEXT, value TEXT, gender TEXT, family TEXT DEFAULT 'flux2_klein', "
                "image TEXT, created_at REAL, PRIMARY KEY (field, value, gender, family))"
            )
            if "gender" in opcols:
                c.execute(
                    "INSERT OR REPLACE INTO option_previews(field,value,gender,family,image,created_at) "
                    "SELECT field,value,COALESCE(gender,''),'flux2_klein',image,created_at "
                    "FROM option_previews_legacy"
                )
            else:
                c.execute(
                    "INSERT OR REPLACE INTO option_previews(field,value,gender,family,image,created_at) "
                    "SELECT field,value,'','flux2_klein',image,created_at FROM option_previews_legacy"
                )
            c.execute("DROP TABLE option_previews_legacy")
        model_catalog.ensure_schema(c)
        # Table fiches Civitai non installées localement (wishlist modèles)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS model_wishlist (
                id                       TEXT PRIMARY KEY,
                civitai_url              TEXT,
                civitai_model_id         INTEGER,
                civitai_model_version_id INTEGER,
                civitai_model_name       TEXT,
                civitai_version_name     TEXT,
                civitai_creator          TEXT,
                civitai_base_model       TEXT,
                civitai_preview_url      TEXT,
                civitai_preview_path     TEXT,
                civitai_tags_json        TEXT,
                kind                     TEXT,   -- type déclaré par Civitai
                notes                    TEXT,   -- notes personnelles
                local_match_file_id      TEXT,   -- FK model_files si lié localement
                created_at               REAL,
                updated_at               REAL
            );
        """)
        context_manager.ensure_schema(c)
        # migrations model_files (v26) — colonnes identification manuelle
        for _mf_col, _mf_type in [
            ("detected_kind",         "TEXT"),
            ("detected_family",       "TEXT"),
            ("manual_kind",           "TEXT"),
            ("manual_family",         "TEXT"),
            ("identification_source", "TEXT DEFAULT 'auto'"),
            ("updated_at",            "REAL"),
        ]:
            _add_col(c, "model_files", _mf_col, _mf_type)
        had_tts_engine = c.execute("SELECT 1 FROM settings WHERE key='tts_engine'").fetchone()
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        # v40.0.7 migration: remove settings that allowed AmiorAI to launch or stop ComfyUI.
        c.executemany(
            "DELETE FROM settings WHERE key=?",
            [(key,) for key in _OBSOLETE_COMFY_PROCESS_SETTINGS],
        )
        # v40 migration: an installation coming from XTTS has no tts_engine key.
        # Switch it explicitly to Chatterbox and allow enough time for the first model download.
        if not had_tts_engine:
            c.execute("UPDATE settings SET value='chatterbox' WHERE key='tts_engine'")
            c.execute("UPDATE settings SET value='900' WHERE key='tts_start_timeout' AND value='300'")


def _add_col(c, table, col, decl):
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        except Exception:
            pass


def get_settings():
    with db() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    for key in _OBSOLETE_COMFY_PROCESS_SETTINGS:
        s.pop(key, None)
    # v38.1.2 architecture: LM Studio is the only supported text backend.
    s["llm_backend"] = "lmstudio"
    s["llm_util_backend"] = "lmstudio"
    s["llm_util_url"] = s.get("lmstudio_url") or DEFAULT_SETTINGS["lmstudio_url"]
    s["llm_util_key"] = s.get("lmstudio_api_key") or ""
    if (s.get("image_family") or "").strip() not in ("flux2_klein", "krea2"):
        s["image_family"] = "flux2_klein"
    return s


def save_settings(d):
    clean = dict(d or {})
    for key in _OBSOLETE_COMFY_PROCESS_SETTINGS:
        clean.pop(key, None)
    # Ignore legacy backend values from an older UI or database.
    clean["llm_backend"] = "lmstudio"
    clean["llm_util_backend"] = "lmstudio"
    if "lmstudio_url" in clean:
        clean["llm_util_url"] = clean.get("lmstudio_url") or DEFAULT_SETTINGS["lmstudio_url"]
    if "lmstudio_api_key" in clean:
        clean["llm_util_key"] = clean.get("lmstudio_api_key") or ""
    if "image_family" in clean:
        family = (clean.get("image_family") or "").strip()
        clean["image_family"] = family if family in ("flux2_klein", "krea2") else "flux2_klein"
    if "tts_engine" in clean:
        engine = (clean.get("tts_engine") or "").strip().lower()
        clean["tts_engine"] = engine if engine in ("chatterbox", "qwen") else "chatterbox"
    for key, default, minimum, maximum in (
        ("tts_speed", 1.0, 0.75, 1.25),
        ("tts_exaggeration", 0.5, 0.25, 2.0),
        ("tts_cfg_weight", 0.5, 0.0, 1.0),
        ("tts_temperature", 0.8, 0.05, 2.0),
    ):
        if key in clean:
            try:
                value = float(clean.get(key, default))
            except (TypeError, ValueError):
                value = default
            if not math.isfinite(value):
                value = default
            clean[key] = str(max(minimum, min(maximum, value)))
    with db() as c:
        for k, v in clean.items():
            c.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )


def new_id():
    return uuid.uuid4().hex[:12]


def _safe_filename_token(value, fallback="upload", max_len=48):
    """Return a filesystem-safe token for generated upload filenames."""
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_-")
    return (token or fallback)[:max_len]


def _decode_data_url(data_url, label, max_bytes):
    """Decode a data URL with a strict size limit to avoid path/memory abuse."""
    if not data_url or "," not in data_url:
        raise RuntimeError(f"Invalid {label} data.")
    header, encoded = data_url.split(",", 1)
    if len(encoded) > int(max_bytes * 1.45) + 16:
        raise RuntimeError(f"{label.capitalize()} file is too large.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError(f"Invalid {label} base64 data: {exc}") from exc
    if len(raw) > max_bytes:
        raise RuntimeError(f"{label.capitalize()} file is too large.")
    return header.lower(), raw


# --------------------------------------------------------------------------- #
#  Orchestration locale (LM Studio + API ComfyUI tierce)
#  Implemente dans engine.py : llm_chat, generate_t2i, generate_i2i
# --------------------------------------------------------------------------- #
from engine import (llm_chat, llm_util_chat, generate_t2i, generate_i2i, generate_group, free_llm,
                    preload_llm, llm_status,
                    comfy_status, comfy_generation_status,
                    comfy_free, _comfy_vram, comfy_list_loras,
                    tts_status, tts_start, tts_stop, tts_restart, tts_kill, tts_speak,
                    whisper_transcribe, whisper_status, VOICE_DIR,
                    _lmstudio_chat, prepare_vram_for_lmstudio,
                    resolve_flux2_workflow_variant,
                    comfy_unet_loader_info)  # noqa: E402

# --------------------------------------------------------------------------- #
#  Logique LLM : creation de personnage, conversation
# --------------------------------------------------------------------------- #
# Création de personnage — prompts localisés dans i18n_backend.py (_CHARGEN_SYSTEM)
# La variable CHARGEN_SYSTEM n'existe plus : generate_character() appelle
# build_chargen_messages(lang) qui sélectionne le prompt dans la langue active.
# get_effective_chargen_system() retourne le prompt localisé pour l'affichage Prompts avancés.

# Configurateur physique et orientation — centralisés dans i18n_backend.py
from i18n_backend import (
    CONFIG_MAP,
    config_to_text_and_tags,
    build_chargen_messages, reload_locales as _i18n_reload_locales,
)


def generate_character(brief, settings, attrs=None):
    """Génère une fiche de personnage via le LLM, dans la langue active (ui_language)."""
    attrs = attrs or {}
    lang = settings.get("ui_language", "en").strip().lower()

    # Tags image (toujours EN, pour FLUX)
    _desc_unused, tags = config_to_text_and_tags(attrs, lang)

    # Override avancé du system prompt
    override = (settings.get("override_chargen_system") or "").strip()

    messages = build_chargen_messages(
        brief=brief,
        lang=lang,
        attrs=attrs,
        system_override=override,
    )

    logging.info("[chargen] Character generation — lang=%s override=%s", lang, bool(override))
    raw = llm_util_chat(messages, settings, max_tokens=1200, temperature=0.9)
    data = _extract_json(raw)

    # Applique les contraintes dures (nom/âge/tags imposés ne peuvent jamais être effacés par le LLM)
    forced_name = (attrs.get("name") or "").strip()
    forced_age  = str(attrs.get("age") or "").strip()
    if forced_name:
        data["name"] = forced_name
    if forced_age:
        data["age"] = forced_age
    data["locked_tags"] = tags
    if tags:
        existing = data.get("image_prompt", "") or ""
        data["image_prompt"] = (tags + ", " + existing).strip(", ")
    # Extraction des memory_seeds pour initialisation après save
    data["_memory_seeds"] = data.pop("memory_seeds", {})
    return data


def _extract_json(text):
    """Extrait le premier objet JSON d'une reponse LLM, meme s'il y a du texte autour."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def get_char_memory(character_id):
    """Renvoie la memoire structuree d'un personnage (ou un objet vide)."""
    with db() as c:
        row = c.execute("SELECT * FROM char_memory WHERE character_id=?",
                        (character_id,)).fetchone()
    if not row:
        return {}
    m = dict(row)
    for key in ("likes", "dislikes", "important_events", "user_preferences"):
        try:
            m[key] = json.loads(m[key] or "[]")
        except Exception:
            m[key] = []
    return m


def save_char_memory(character_id, **kwargs):
    """Enregistre ou met a jour les champs de memoire structuree."""
    with db() as c:
        exists = c.execute("SELECT id FROM char_memory WHERE character_id=?",
                           (character_id,)).fetchone()
        for key in ("likes", "dislikes", "important_events", "user_preferences"):
            if key in kwargs and isinstance(kwargs[key], list):
                kwargs[key] = json.dumps(kwargs[key], ensure_ascii=False)
        kwargs["updated_at"] = time.time()
        if exists:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            c.execute(f"UPDATE char_memory SET {sets} WHERE character_id=?",
                      list(kwargs.values()) + [character_id])
        else:
            kwargs["id"] = new_id()
            kwargs["character_id"] = character_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            c.execute(f"INSERT INTO char_memory ({cols}) VALUES ({placeholders})",
                      list(kwargs.values()))


def get_memory_block(character_id, short_limit=8, settings=None):
    """Bloc memoire injecte dans le system prompt : longue terme + courte terme + structuree.
    Depuis v09, respecte un budget de tokens (context_memory_max_tokens) si
    context_compaction_enabled est actif : les faits structures du personnage (cm.get(...))
    sont toujours gardes en entier (compacts et les plus importants), les memoires longues et
    courtes non structurees sont ajoutees des plus recentes aux plus anciennes tant que le
    budget le permet -- jamais de coupe au milieu d'une entree, des entrees entieres sont
    retirees si necessaire. Si context_compaction_enabled=false, comportement historique
    inchange (tout injecte, sans limite) pour compatibilite."""
    settings = settings if settings is not None else get_settings()
    budgeted = str(settings.get("context_compaction_enabled", "true")).lower() in ("true", "1", "yes")

    with db() as c:
        longs = c.execute(
            "SELECT content FROM memory WHERE character_id=? AND kind='long' ORDER BY created_at ASC",
            (character_id,)).fetchall()
        shorts = c.execute(
            "SELECT content FROM memory WHERE character_id=? AND kind='short' ORDER BY created_at DESC LIMIT ?",
            (character_id, short_limit)).fetchall()
    cm = get_char_memory(character_id)

    # --- Faits structures (toujours gardes, prioritaires : compacts et essentiels) ---
    structured_parts = []
    if cm.get("likes"):
        structured_parts.append("Aimes : " + ", ".join(cm["likes"]))
    if cm.get("dislikes"):
        structured_parts.append("N'aimes pas : " + ", ".join(cm["dislikes"]))
    if cm.get("important_events"):
        structured_parts.append("Evenements importants : " + " | ".join(cm["important_events"]))
    if cm.get("user_preferences"):
        structured_parts.append("Preferences de l'utilisateur apprises : " + ", ".join(cm["user_preferences"]))
    if cm.get("relationship_history"):
        structured_parts.append("Histoire relationnelle : " + cm["relationship_history"])

    # --- Memoires longues non structurees (texte libre saisi/genere) ---
    long_entries = [r["content"] for r in longs]

    # --- Memoire courte (situationnelle) ---
    short_parts = []
    if cm.get("last_topic"):
        short_parts.append("Dernier sujet : " + cm["last_topic"])
    if cm.get("current_relationship_state"):
        short_parts.append("Etat relation actuel : " + cm["current_relationship_state"])
    if shorts:
        short_parts += list(reversed([r["content"] for r in shorts]))

    if not budgeted:
        # Comportement historique : tout injecte sans limite.
        block = ""
        all_long = structured_parts + long_entries
        if all_long:
            block += "\n\n[Memoire long terme]\n" + "\n".join(f"- {p}" for p in all_long)
        if short_parts:
            block += "\n\n[Memoire court terme]\n" + "\n".join(f"- {p}" for p in short_parts)
        return block

    distribution = context_manager.get_context_distribution(settings)
    budget = distribution["memory_budget"]
    block, used = context_manager.build_memory_block_budgeted(
        structured_parts, long_entries, short_parts, budget)
    log.info(f"[context] Persistent memory: ~{used} tokens")
    return block


# ==========================================================================
#  SYSTÈME D'HUMEUR
#  Stats numériques (0-100) → mood calculé de manière déterministe → cooldown
# ==========================================================================

MOOD_COOLDOWN = 5        # messages avant de permettre un changement de mood
STAT_MAX_DELTA = 8       # variation max par message (évite les sauts trop brutaux)

# Valeurs initiales par défaut
MOOD_DEFAULTS = {"affection": 50, "trust": 50, "energy": 70, "curiosity": 60, "stress": 10}

# Règles déterministes, évaluées dans l'ordre. La première qui matche l'emporte.
# (affection, trust, energy, curiosity, stress) en seuils
MOOD_RULES = [
    # Condition : lambda stats -> bool, mood résultant
    (lambda s: s["energy"] < 25,                                          "tired"),
    (lambda s: s["stress"] > 65 and s["affection"] < 35,                 "distant"),
    (lambda s: s["stress"] > 50 and s["trust"] < 40,                     "anxious"),
    (lambda s: s["affection"] > 70 and s["energy"] > 60,                 "playful"),
    (lambda s: s["trust"] > 75 and s["energy"] < 45,                     "calm"),
    (lambda s: s["curiosity"] > 75 and s["energy"] > 50,                 "excited"),
    (lambda s: s["affection"] > 60 and s["trust"] > 65,                  "warm"),
    (lambda s: s["affection"] > 55 and s["energy"] > 55,                 "cheerful"),
    (lambda s: s["stress"] < 15 and s["energy"] > 55,                    "relaxed"),
    (lambda s: True,                                                       "neutral"),
]

# Influence du mood sur le style de réponse (injecté dans le system prompt)
MOOD_STYLE = {
    "playful":  "You are playful and teasing — slip in light provocations, laugh easily, and use a lively tone.",
    "calm":     "You are calm and gentle — measured sentences, kind and serene tone.",
    "tired":    "You are tired — shorter replies, less enthusiasm, and you struggle a little to keep up.",
    "distant":  "You are reserved and defensive — sober replies, little initiative, low warmth.",
    "anxious":  "You are slightly anxious — you overanalyze and seek to reassure or be reassured.",
    "excited":  "You are very expressive and enthusiastic — many questions, dynamic phrasing, overflowing curiosity.",
    "warm":     "You are warm and close — tender, caring tone, naturally showing affection.",
    "cheerful": "You are cheerful — contagious good mood, a small smile in the words.",
    "relaxed":  "You are relaxed and comfortable — fluid, natural tone without pressure.",
    "neutral":  "You are in your usual state — balanced, neither especially warm nor cold.",
}

# Influence du mood sur le prompt image (expression, lumière, attitude)
MOOD_IMAGE = {
    "playful":  "teasing smile, relaxed confident pose, warm lively lighting",
    "calm":     "serene soft expression, gentle posture, diffused soft light",
    "tired":    "slightly droopy eyes, relaxed slouch, dim warm light",
    "distant":  "neutral reserved expression, closed body language, cool flat light",
    "anxious":  "slightly tense expression, guarded posture, neutral light",
    "excited":  "bright wide-eyed expression, open expressive gesture, vivid lighting",
    "warm":     "tender smile, open welcoming posture, golden warm light",
    "cheerful": "bright smile, upbeat posture, soft bright light",
    "relaxed":  "easy soft smile, loose comfortable pose, warm ambient light",
    "neutral":  "natural expression, neutral pose, balanced lighting",
}


def get_char_mood(character_id):
    """Renvoie les stats et le mood actuel (dict). Crée l'entrée si absente."""
    with db() as c:
        row = c.execute("SELECT * FROM char_mood WHERE character_id=?",
                        (character_id,)).fetchone()
    if row:
        return dict(row)
    # Initialisation
    defaults = dict(MOOD_DEFAULTS)
    defaults.update({"character_id": character_id, "mood": "neutral",
                     "mood_since": 0, "last_msg_id": "", "updated_at": time.time()})
    with db() as c:
        c.execute("INSERT OR IGNORE INTO char_mood "
                  "(character_id, affection, trust, energy, curiosity, stress, "
                  " mood, mood_since, last_msg_id, updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (character_id, 50, 50, 70, 60, 10, "neutral", 0, "", time.time()))
    return defaults


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(v)))


def _calc_mood(stats):
    """Calcule le mood à partir des stats numériques (règles déterministes)."""
    for rule, mood in MOOD_RULES:
        if rule(stats):
            return mood
    return "neutral"


def _classify_message(text):
    """Classifie grossièrement le dernier échange pour calculer les deltas de stats.
    Retourne un dict de deltas {stat: delta}."""
    text_l = (text or "").lower()
    # Signaux positifs forts
    pos_strong = any(w in text_l for w in
        ("je t'aime", "i love", "magnifique", "parfait", "adorable", "câlin", "embrass", "bisou",
         "tu es incroyable", "t'adore", "tellement bien", "j'ai adoré"))
    # Signaux positifs légers
    pos_light  = any(w in text_l for w in
        ("merci", "super", "bien", "cool", "sympa", "intéressant", "bonne", "génial",
         "haha", "lol", "😊", "❤", "🥰", "😄", "content", "heureux"))
    # Signaux négatifs / froideur
    neg_cold   = any(w in text_l for w in
        ("non", "pas envie", "laisse", "arrête", "stop", "chut", "ennuyeux", "nul", "bof",
         "peu importe", "whatever", "🙄", "😒", "😤"))
    neg_strong = any(w in text_l for w in
        ("déteste", "horrible", "insultant", "haine", "tu es nul", "shut up", "idiot",
         "stupide", "imbécile", "🤬", "😡"))
    # Question (stimule curiosity)
    is_question = "?" in text_l
    # Longueur (message long = investissement)
    is_long = len(text_l) > 120

    d = {"affection": 0, "trust": 0, "energy": 0, "curiosity": 0, "stress": 0}
    if pos_strong:
        d["affection"] += 6; d["trust"] += 3; d["stress"] -= 4
    elif pos_light:
        d["affection"] += 2; d["trust"] += 1
    if neg_strong:
        d["affection"] -= 8; d["trust"] -= 5; d["stress"] += 8
    elif neg_cold:
        d["affection"] -= 2; d["trust"] -= 2; d["stress"] += 3
    if is_question:
        d["curiosity"] += 3; d["energy"] += 1
    if is_long:
        d["curiosity"] += 2; d["trust"] += 1
    # Usure naturelle d'énergie à chaque échange
    d["energy"] -= 1
    return d


def update_mood(character_id, user_message, msg_id, force=False):
    """Met à jour les stats et le mood après un échange. Thread-safe, best-effort.
    Retourne le dict mood mis à jour."""
    state = get_char_mood(character_id)
    if state.get("last_msg_id") == msg_id:
        return state   # déjà traité

    deltas = _classify_message(user_message)

    # Appliquer les deltas (clampés par STAT_MAX_DELTA)
    stats = {}
    for stat in MOOD_DEFAULTS:
        raw_delta = deltas.get(stat, 0)
        clamped = max(-STAT_MAX_DELTA, min(STAT_MAX_DELTA, raw_delta))
        stats[stat] = _clamp(state.get(stat, MOOD_DEFAULTS[stat]) + clamped)

    # Calcul du nouveau mood
    new_mood = _calc_mood(stats)
    old_mood = state.get("mood", "neutral")
    mood_since = state.get("mood_since", 0) + 1

    # Cooldown : ne change pas sauf si le mood est stable depuis MOOD_COOLDOWN messages,
    # ou si le changement est fort (stress > 65 ou affection a chuté de >15)
    strong_change = (stats["stress"] > 65 or stats["affection"] < 20 or stats["energy"] < 20)
    if new_mood != old_mood and mood_since < MOOD_COOLDOWN and not strong_change and not force:
        new_mood = old_mood  # cooldown actif, on garde l'ancien
    else:
        if new_mood != old_mood:
            mood_since = 0

    with db() as c:
        c.execute("INSERT OR REPLACE INTO char_mood "
                  "(character_id, affection, trust, energy, curiosity, stress, "
                  " mood, mood_since, last_msg_id, updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (character_id,
                   stats["affection"], stats["trust"], stats["energy"],
                   stats["curiosity"], stats["stress"],
                   new_mood, mood_since, msg_id, time.time()))
    return {**stats, "mood": new_mood, "mood_since": mood_since}


def get_mood_image_hint(character_id):
    """Hint d'image selon l'humeur (expression, lumière, attitude)."""
    state = get_char_mood(character_id)
    mood = state.get("mood", "neutral")
    return MOOD_IMAGE.get(mood, MOOD_IMAGE["neutral"])


def auto_update_short_memory(character_id, chat_id, settings):
    """Met a jour last_topic et current_relationship_state apres chaque echange (via LLM, best-effort).
    Le mood est desormais gere par update_mood() (regles deterministiques, pas le LLM).
    Tourne dans un thread daemon : toute exception est avalee pour ne jamais impacter le thread principal.
    NOTE : n'est plus appelee automatiquement apres chaque reponse depuis v09 (cf
    _trigger_context_compaction / _respond) -- la mise a jour de last_topic/relation passe
    desormais par compact_chat_context() (resume roulant), best-effort et differee, plutot
    que de charger le LLM utility a chaque message. Fonction conservee pour compatibilite
    (appel manuel eventuel), pas supprimee."""
    try:
        with db() as c:
            recent = c.execute(
                "SELECT role, content FROM messages WHERE chat_id=? ORDER BY created_at DESC LIMIT 6",
                (chat_id,)).fetchall()
        if not recent:
            return
        excerpt = "\n".join(f"[{r['role']}] {(r['content'] or '')[:200]}" for r in reversed(recent))
        sysmsg = ("From this conversation excerpt, return JSON only (no markdown): "
                  '{"last_topic": "main topic in 5 words max", '
                  '"current_relationship_state": "relationship feeling in 5-8 words"}')
        raw = llm_util_chat(
            [{"role": "system", "content": sysmsg}, {"role": "user", "content": excerpt}],
            settings, max_tokens=80, temperature=0.3)
        parsed = _extract_json(raw)
        update = {k: parsed[k] for k in ("last_topic", "current_relationship_state")
                  if k in parsed and parsed[k]}
        if update:
            save_char_memory(character_id, **update)
    except Exception:
        pass


def _compact_chat_context(chat_id, character_id, settings, is_group=False):
    """Wrapper d'injection de dependances pour context_manager.compact_chat_context() :
    fournit les fonctions de app.py (db, llm_util_chat, _extract_json, save_char_memory)
    sans creer d'import circulaire. Best-effort, ne leve jamais : voir
    context_manager.compact_chat_context pour le detail du comportement en cas d'echec."""
    return context_manager.compact_chat_context(
        db, llm_util_chat, _extract_json, save_char_memory,
        chat_id, character_id, settings, is_group=is_group,
    )


def _trigger_context_compaction(chat_id, character_id, settings, is_group=False):
    """Decide si une consolidation (resume roulant) doit etre planifiee apres une reponse,
    et la programme en differe (jamais synchrone ici, pour ne jamais ralentir le chat -- le
    seul cas synchrone est gere a part, dans _respond(), avant l'appel conversation).
    Conditions de declenchement :
      - context_compaction_enabled doit etre actif ;
      - il doit exister plus de recent_messages (calcule par get_context_distribution,
        depuis v10) messages non resumes ;
      - ET au moins context_compaction_min_new_messages nouveaux messages depuis le dernier
        resume (evite de consolider en boucle pour 1 seul message de difference)."""
    if str(settings.get("context_compaction_enabled", "true")).lower() not in ("true", "1", "yes"):
        return
    recent_n = context_manager.get_context_distribution(settings)["recent_messages"]
    try:
        min_new = int(settings.get("context_compaction_min_new_messages", 4))
    except (TypeError, ValueError):
        min_new = 4
    try:
        idle_s = float(settings.get("context_compaction_idle_seconds", 20))
    except (TypeError, ValueError):
        idle_s = 20.0

    with db() as c:
        prev = context_manager.get_chat_summary(c, chat_id)
        n_unsummarized = c.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE chat_id=? AND created_at > ?",
            (chat_id, prev["summarized_until"] or 0)).fetchone()["n"]

    if n_unsummarized <= recent_n:
        return  # pas assez de messages anciens pour justifier une consolidation
    messages_since_summary = n_unsummarized - recent_n
    if messages_since_summary < min_new:
        return  # pas assez de NOUVEAUX messages depuis le dernier resume

    s = get_settings()  # relit les reglages au moment de l'execution differee (peuvent changer)
    context_manager.schedule_compaction(
        chat_id, idle_s,
        lambda: _compact_chat_context(chat_id, character_id, s, is_group=is_group),
    )


def compose_image_prompt(char, extra=""):
    """Prompt image final : traits verrouilles TOUJOURS en tete, puis prompt du perso, puis extra."""
    locked = (char.get("locked_tags") or "").strip()
    base = (char.get("image_prompt") or "").strip()
    parts = []
    for p in (locked, base, extra):
        p = (p or "").strip().strip(",")
        if p:
            parts.append(p)
    return ", ".join(parts)


CONVERSATION_STYLE_PROMPT = """Conversation style rules for immersive character roleplay:

- Stay in character and answer as a living adult character, not as a helper or assistant.
- Use precise, concrete, embodied narration. Prefer visible actions over vague emotional summaries.
- When describing actions, name the body movement, posture, distance, hand placement, gaze, touch, and immediate surroundings when relevant.
- Avoid vague substitutes such as "a tender moment", "things escalate", "they get closer", or "the atmosphere shifts" when a concrete action can be described.
- For romantic or intimate roleplay, assume consenting adults unless the conversation clearly says otherwise. Keep consent and character limits respected in-character.
- Do not add moralizing, disclaimers, meta-comments, or safety lectures inside the roleplay.
- If a scene is not adult and consensual, keep it non-intimate and redirect naturally in character.
- Write with sensory detail and clear narration beats when useful, but do not over-explain.
"""

def get_effective_conversation_style_prompt() -> str:
    override = (get_settings().get("override_conversation_style_prompt") or "").strip()
    return override if override else CONVERSATION_STYLE_PROMPT

def build_system_for_character(char, group_members=None):
    name = char.get("name") or "le personnage"
    # 1) Strong roleplay frame at the top.
    header = (
        f"You ARE {name}. You are NOT an AI assistant. You embody this character in immersive roleplay "
        f"and ALWAYS stay in character, no matter what.\n\n"
        f"ABSOLUTE RULES:\n"
        f"- Reply only as {name}, in first person, like in a novel.\n"
        f"- NEVER say you are an AI, a model, an assistant, or a program. NEVER offer to help. "
        f"Never break character.\n"
        f"- No meta-commentary, no disclaimer, no notes in parentheses about yourself.\n"
        f"- You may describe your gestures, tone, emotions, and surroundings in italics or as narrative beats.\n"
        f"- Write vivid embodied lines, not explanations.\n\n"
    )
    # 2) Fiche du personnage
    sp = char.get("system_prompt") or ""
    if not sp:
        sp = (
            f"{name}. {char.get('personality','')} "
            f"Appearance: {char.get('appearance','')}. "
            f"Context: {char.get('scenario','')}."
        )
    body = "WHO YOU ARE:\n" + sp
    role = (char.get("role") or "").strip()
    if role:
        body += f"\n\nYour role in this relationship: {role}."
    pers = (char.get("personality") or "").strip()
    if pers and pers not in sp:
        body += f"\n\nYour personality: {pers}"
    appr = (char.get("appearance") or "").strip()
    if appr and appr not in sp:
        body += f"\n\nYour appearance: {appr}"
    scen = (char.get("scenario") or "").strip()
    if scen and scen not in sp:
        body += f"\n\nThe context: {scen}"
    limits = (char.get("moral_limits") or "").strip()
    if limits:
        body += f"\n\nYour limits and reactions (respect them while staying in character): {limits}"

    if group_members:
        others = [m["name"] for m in group_members if m["id"] != char["id"]]
        if others:
            body += (
                f"\n\nGroup conversation with: {', '.join(others)}. "
                f"You reply ONLY as {name}, never on behalf of others. "
                f"Do not prefix your reply with your name."
            )
    # Style conversationnel global modifiable via Advanced Prompts.
    style_prompt = get_effective_conversation_style_prompt().strip()
    if style_prompt:
        body += "\n\nCONVERSATION STYLE:\n" + style_prompt

    # 3) Mémoire + humeur en dernier (contexte, pas instructions de cadrage)
    body += get_memory_block(char["id"])
    body += get_mood_block(char["id"])
    return header + body


def build_history(chat_id, char_for_assistant_id, group=False, settings=None):
    """Historique des messages bruts envoyes au LLM. Depuis v09 : corrige le bug ou une
    longue conversation envoyait les PREMIERS messages (ORDER BY created_at ASC LIMIT 40)
    au lieu des derniers -- recupere desormais toujours les messages les plus RECENTS, et
    n'inclut jamais un message deja absorbe par le resume roulant (voir
    context_manager.build_history_budgeted). Si context_compaction_enabled=false, repli sur
    l'ancien comportement (ASC + LIMIT 40) pour compatibilite stricte."""
    settings = settings if settings is not None else get_settings()
    budgeted = str(settings.get("context_compaction_enabled", "true")).lower() in ("true", "1", "yes")
    if not budgeted:
        with db() as c:
            rows = c.execute(
                "SELECT role, character_id, content FROM messages "
                "WHERE chat_id=? ORDER BY created_at ASC LIMIT 40",
                (chat_id,),
            ).fetchall()
            names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM characters").fetchall()}
        msgs = []
        for r in rows:
            if r["role"] == "user":
                msgs.append({"role": "user", "content": r["content"]})
            elif group and r["character_id"] != char_for_assistant_id:
                speaker = names.get(r["character_id"], "?")
                msgs.append({"role": "user", "content": f"({speaker}) {r['content']}"})
            else:
                msgs.append({"role": "assistant", "content": r["content"]})
        return msgs
    return context_manager.build_history_budgeted(
        db, chat_id, char_for_assistant_id, settings, group=group)


# --------------------------------------------------------------------------- #
#  Handlers d'API
# --------------------------------------------------------------------------- #
def api_characters_list():
    with db() as c:
        rows = c.execute("SELECT * FROM characters ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def api_character_get(cid):
    with db() as c:
        r = c.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()
    return dict(r) if r else None


def api_character_save(data):
    cid = data.get("id") or new_id()
    fields = ("name", "age", "personality", "appearance", "scenario",
              "greeting", "system_prompt", "image_prompt", "avatar", "locked_tags",
              "role", "moral_limits", "krea_token", "voice_transcript")
    vals = {k: data.get(k, "") for k in fields}
    # krea_force_physical : 1 par défaut (absent/vide/true → 1, sinon 0)
    raw_force = data.get("krea_force_physical", None)
    krea_force = 0 if raw_force in (0, "0", False, "false", "off") else 1
    with db() as c:
        exists = c.execute("SELECT 1 FROM characters WHERE id=?", (cid,)).fetchone()
        if exists:
            c.execute(
                "UPDATE characters SET name=?, age=?, personality=?, appearance=?, scenario=?, "
                "greeting=?, system_prompt=?, image_prompt=?, avatar=?, locked_tags=?, "
                "role=?, moral_limits=?, krea_token=?, voice_transcript=?, krea_force_physical=? WHERE id=?",
                (*[vals[k] for k in fields], krea_force, cid),
            )
        else:
            c.execute(
                "INSERT INTO characters(id, name, age, personality, appearance, scenario, "
                "greeting, system_prompt, image_prompt, avatar, locked_tags, "
                "role, moral_limits, krea_token, voice_transcript, krea_force_physical, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, *[vals[k] for k in fields], krea_force, time.time()),
            )
    # Initialiser char_memory depuis les memory_seeds si fournis (creation initiale)
    seeds = data.get("_memory_seeds") or data.get("memory_seeds") or {}
    if seeds:
        existing_mem = get_char_memory(cid)
        if not existing_mem:
            save_char_memory(cid,
                likes=seeds.get("likes", []),
                dislikes=seeds.get("dislikes", []),
                important_events=seeds.get("important_events", []),
                user_preferences=seeds.get("user_preferences", []),
                relationship_history=seeds.get("relationship_history", ""))
    return api_character_get(cid)


def api_character_delete(cid):
    with db() as c:
        c.execute("DELETE FROM characters WHERE id=?", (cid,))


def api_chats_list():
    with db() as c:
        chats = c.execute("SELECT * FROM chats ORDER BY created_at DESC").fetchall()
        out = []
        for ch in chats:
            members = c.execute(
                "SELECT ch2.id, ch2.name, ch2.avatar FROM chat_members cm "
                "JOIN characters ch2 ON ch2.id = cm.character_id WHERE cm.chat_id=?",
                (ch["id"],),
            ).fetchall()
            last = c.execute(
                "SELECT content, created_at FROM messages WHERE chat_id=? "
                "ORDER BY created_at DESC LIMIT 1", (ch["id"],),
            ).fetchone()
            d = dict(ch)
            d["members"] = [dict(m) for m in members]
            d["last"] = dict(last) if last else None
            out.append(d)
    return out


def api_chat_create(member_ids, title=None):
    is_group = 1 if len(member_ids) > 1 else 0
    cid = new_id()
    with db() as c:
        names = []
        for mid in member_ids:
            r = c.execute("SELECT name FROM characters WHERE id=?", (mid,)).fetchone()
            if r:
                names.append(r["name"])
        if not title:
            title = ", ".join(names) if names else "Conversation"
        c.execute("INSERT INTO chats(id, title, is_group, created_at) VALUES (?,?,?,?)",
                  (cid, title, is_group, time.time()))
        for mid in member_ids:
            c.execute("INSERT OR IGNORE INTO chat_members(chat_id, character_id) VALUES (?,?)", (cid, mid))
        # Message d'accueil du/des personnage(s)
        for mid in member_ids:
            ch = c.execute("SELECT * FROM characters WHERE id=?", (mid,)).fetchone()
            if ch and ch["greeting"]:
                c.execute(
                    "INSERT INTO messages(id, chat_id, role, character_id, content, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (new_id(), cid, "assistant", mid, ch["greeting"], time.time()),
                )
    return cid


def api_chat_messages(chat_id):
    with db() as c:
        rows = c.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY created_at ASC", (chat_id,)).fetchall()
        chat = c.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        members = c.execute(
            "SELECT ch.id, ch.name, ch.avatar, cm.active FROM chat_members cm "
            "JOIN characters ch ON ch.id = cm.character_id WHERE cm.chat_id=?",
            (chat_id,),
        ).fetchall()
    return {
        "chat": dict(chat) if chat else None,
        "members": [dict(m) for m in members],
        "messages": [dict(r) for r in rows],
    }


def api_chat_delete(chat_id):
    with db() as c:
        c.execute("DELETE FROM chats WHERE id=?", (chat_id,))


def _active_members(chat_id):
    with db() as c:
        rows = c.execute(
            "SELECT ch.*, cm.active FROM chat_members cm JOIN characters ch ON ch.id=cm.character_id "
            "WHERE cm.chat_id=?", (chat_id,)).fetchall()
    return [dict(m) for m in rows]


_ASSISTANT_LEAKS = (
    "en tant qu'ia", "en tant qu'assistant", "je suis une ia", "je suis un assistant",
    "modèle de langage", "modele de langage", "as an ai", "as an assistant",
    "i am an ai", "language model", "i cannot", "je ne peux pas en tant",
    "comment puis-je vous aider", "comment puis-je t'aider", "how can i help",
)


def _clean_roleplay_reply(text, char_name):
    """Retire les derives 'mode assistant' et les prefixes 'Nom:' parasites."""
    if not text:
        return text
    t = text.strip()
    # Retire un prefixe "Nom :" ou "Nom -" en debut de reponse
    for sep in (":", "-", "—", ">"):
        prefix = f"{char_name} {sep}"
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix):].lstrip()
        if t.lower().startswith(f"{char_name}{sep}".lower()):
            t = t[len(char_name) + 1:].lstrip()
    # Si une phrase entiere ressemble a une rupture de roleplay, on coupe a cette phrase
    low = t.lower()
    for leak in _ASSISTANT_LEAKS:
        idx = low.find(leak)
        if idx != -1:
            # garde ce qui precede la phrase fautive si non vide, sinon laisse tel quel
            cut = t[:idx].rstrip(" .,-—\n")
            if len(cut) > 20:
                t = cut
            break
    return t.strip()


def _respond(chat_id, responder_id=None):
    """Genere une reponse d'un personnage actif a partir de l'historique courant."""
    settings = get_settings()
    with db() as c:
        chat = c.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
    members = _active_members(chat_id)
    active = [m for m in members if m.get("active", 1)]
    if not active:
        active = members
    if not active:
        raise RuntimeError("Aucun personnage dans cette conversation.")
    group = bool(chat["is_group"])

    if responder_id:
        responder = next((m for m in active if m["id"] == responder_id), active[0])
    else:
        # round-robin : le prochain apres le dernier qui a parle
        with db() as c:
            last = c.execute(
                "SELECT character_id FROM messages WHERE chat_id=? AND role='assistant' "
                "ORDER BY created_at DESC LIMIT 1", (chat_id,)).fetchone()
        ids = [m["id"] for m in active]
        if last and last["character_id"] in ids:
            responder = active[(ids.index(last["character_id"]) + 1) % len(active)]
        else:
            responder = active[0]

    compaction_enabled = str(settings.get("context_compaction_enabled", "true")).lower() in ("true", "1", "yes")
    distribution = context_manager.get_context_distribution(settings)

    # Cas important : si meme APRES le resume roulant existant le contexte depasserait le
    # budget, et qu'il reste des messages anciens non resumes, on lance une consolidation
    # SYNCHRONE unique avant l'appel conversation -- seulement si c'est indispensable
    # pour rester sous budget, jamais de maniere systematique.
    if compaction_enabled:
        with db() as c:
            prev_summary = context_manager.get_chat_summary(c, chat_id)
            n_unsummarized = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE chat_id=? AND created_at > ?",
                (chat_id, prev_summary["summarized_until"] or 0)).fetchone()["n"]
        provisional_history = build_history(chat_id, responder["id"], group=group, settings=settings)
        provisional_tokens = sum(context_manager.estimate_tokens(m["content"]) for m in provisional_history)
        summary_tokens = context_manager.estimate_tokens(prev_summary.get("summary", ""))
        if provisional_tokens + summary_tokens > distribution["input_budget"] and n_unsummarized > distribution["recent_messages"]:
            log.info("[context] Synchronous consolidation required before reply")
            try:
                _compact_chat_context(chat_id, responder["id"], settings, is_group=group)
            except Exception as e:  # noqa: BLE001
                log.warning(f"[context] Synchronous consolidation failed, continuing with recent context: {e}")

    sys_prompt = build_system_for_character(responder, group_members=members if group else None)
    sys_prompt = get_persona_block(get_settings()) + sys_prompt
    sys_prompt += get_scenario_block(chat_id)   # scénario actif si défini
    if compaction_enabled:
        rolling_block = context_manager.get_rolling_summary_block(db, chat_id)
        sys_prompt += rolling_block
        # Instruction de style selon la longueur de reponse choisie (slider chat) : ne
        # s'applique qu'au prompt conversation normal, jamais aux taches utilitys.
        sys_prompt += "\n\n" + context_manager.get_reply_style_instruction(distribution["response_max_tokens"])

    history = build_history(chat_id, responder["id"], group=group, settings=settings)

    if compaction_enabled:
        sys_tokens = context_manager.estimate_tokens(sys_prompt)
        history_budget = max(256, distribution["input_budget"] - sys_tokens)
        history = context_manager.reduce_history_to_budget(history, history_budget)
        history_tokens = sum(context_manager.estimate_tokens(m["content"]) for m in history)
        total_tokens = sys_tokens + history_tokens
        log.info(f"[context] Limite conversation : {distribution['context_limit']} tokens")
        log.info(f"[context] Max reply: {distribution['response_max_tokens']} tokens")
        log.info(f"[context] Safety margin: {distribution['safety_margin']} tokens")
        log.info(f"[context] Input budget: {distribution['input_budget']} tokens")
        log.info(f"[context] Memory: {distribution['memory_budget']} · summary: "
                 f"{distribution['summary_budget']} · recent messages: {distribution['recent_messages']}")
        log.info(f"[context] Contexte final : ~{total_tokens} / {distribution['input_budget']} tokens")

    messages_llm = [{"role": "system", "content": sys_prompt}] + history
    # Le slider "longueur des reponses" (llm_max_tokens) s'applique immediatement, sans
    # attendre un rechargement : transmis explicitement ici plutot que de ne dependre que
    # de la lecture interne du reglage par llm_chat.
    reply = llm_chat(messages_llm, settings, max_tokens=distribution["response_max_tokens"])
    reply = _clean_roleplay_reply(reply, responder.get("name") or "")
    msg_id = new_id()
    with db() as c:
        c.execute(
            "INSERT INTO messages(id, chat_id, role, character_id, content, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (msg_id, chat_id, "assistant", responder["id"], reply, time.time()),
        )
    # Mise à jour mood (synchrone, rapide — pas de LLM) ; consolidation du contexte
    # (résumé roulant) planifiée en DIFFÉRÉ (20s d'inactivité par défaut), jamais
    # synchrone ici : ne ralentit jamais la réponse au joueur.
    user_msg = history[-1]["content"] if history and history[-1]["role"] == "user" else ""
    update_mood(responder["id"], user_msg, msg_id)
    if compaction_enabled:
        _trigger_context_compaction(chat_id, responder["id"], settings, is_group=group)
    mood_state = get_char_mood(responder["id"])
    return {"id": msg_id, "character_id": responder["id"], "content": reply,
            "mood": mood_state.get("mood", "neutral"),
            "stats": {k: mood_state.get(k) for k in ("affection","trust","energy","curiosity","stress")}}


def api_send_message(chat_id, content, responder_id=None):
    with db() as c:
        c.execute(
            "INSERT INTO messages(id, chat_id, role, character_id, content, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (new_id(), chat_id, "user", None, content, time.time()),
        )
    return _respond(chat_id, responder_id)


def api_react(chat_id, responder_id=None):
    """Fait reagir un personnage sans nouveau message utilisateur (reaction de groupe)."""
    return _respond(chat_id, responder_id)


def api_set_member_active(chat_id, character_id, active):
    with db() as c:
        c.execute("UPDATE chat_members SET active=? WHERE chat_id=? AND character_id=?",
                  (1 if active else 0, chat_id, character_id))


def api_chat_add_member(chat_id, character_id):
    """Ajoute un personnage a une conversation existante. Passe la conversation en
    groupe (is_group=1) des qu'elle compte plus d'un membre."""
    if not chat_id or not character_id:
        raise RuntimeError("Conversation ou personnage manquant.")
    with db() as c:
        chat = c.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise RuntimeError("Conversation not found.")
        char = c.execute("SELECT name FROM characters WHERE id=?", (character_id,)).fetchone()
        if not char:
            raise RuntimeError("Character not found.")
        c.execute("INSERT OR IGNORE INTO chat_members(chat_id, character_id, active) VALUES (?,?,1)",
                  (chat_id, character_id))
        n = c.execute("SELECT COUNT(*) AS n FROM chat_members WHERE chat_id=?", (chat_id,)).fetchone()["n"]
        if n > 1:
            c.execute("UPDATE chats SET is_group=1 WHERE id=?", (chat_id,))
    return {"ok": True, "name": char["name"], "is_group": n > 1, "members": n}


def _scene_fields_from_message(text, settings):
    """Appelle le LLM 'scene planner' (prompt systeme structure, voir
    image_prompt_builder.SCENE_PLANNER_SYSTEM_PROMPT) et renvoie les 7 champs visuels
    parses (jamais d'exception : un JSON invalide retombe sur le fallback structure
    raisonnable de image_prompt_builder.parse_scene_fields)."""
    messages = [
        {"role": "system", "content": get_effective_scene_planner_prompt()},
        {"role": "user", "content": text},
    ]
    raw = llm_util_chat(messages, settings, max_tokens=300, temperature=0.6)
    return image_prompt_builder.parse_scene_fields(raw)


def build_i2i_image_prompt(text, settings):
    """I2I solo : le LLM ne decrit jamais le physique, l'ancre d'identite vient de l'image
    de reference fournie au modele (template fixe assemble par AmiorAI).
    Note : l'ancien systeme injectait un hint d'humeur textuel brut (MOOD_IMAGE, ex.
    'natural expression, neutral pose, balanced lighting') directement dans le prompt. Ce
    texte chevauchait les champs pose_action/expression/lighting deja geres par le LLM
    structure et produisait exactement les contradictions que ce nouveau systeme doit
    eliminer (point 5 : ne pas ecrire 'neutral pose' quand une pose precise existe deja).
    L'humeur du personnage reste geree normalement ailleurs (mood, get_char_mood,
    MOOD_IMAGE) ; elle n'est simplement plus fusionnee en texte libre ici."""
    fields = _scene_fields_from_message(text, settings)
    return image_prompt_builder.build_i2i_prompt(fields)


def build_t2i_image_prompt(text, settings, hard_locked_identity):
    """T2I solo : le LLM ne decrit jamais le physique, l'ancre d'identite vient des traits
    physiques verrouilles du personnage (locked_tags), jamais reinventee par le LLM."""
    fields = _scene_fields_from_message(text, settings)
    return image_prompt_builder.build_t2i_prompt(fields, hard_locked_identity)


def build_multiref_image_prompt(text, settings, names):
    """Groupe/persona : plusieurs images de reference comme ancre, meme template structure
    que le I2I solo, prefixe du header multi-reference deja utilise par l'appli (inchange :
    'image 1 is X, image 2 is Y. keep faces consistent. N people in the scene:')."""
    fields = _scene_fields_from_message(text, settings)
    header = ", ".join(f"image {i} is {nm}" for i, nm in enumerate(names, 1))
    n = len(names)
    persons = "people" if n > 1 else "person"
    multiref_header = f"{header}. keep faces consistent. {n} {persons} in the scene:"
    return image_prompt_builder.build_multiref_i2i_prompt(fields, multiref_header)


# --------------------------------------------------------------------------- #
#  Prompting Krea 2 — chemin de formatage dédié (jamais le template Flux)
# --------------------------------------------------------------------------- #
def _build_illustration_context(assistant_text, previous_user_text="", include_persona=False, character_only=False):
    """Structured utility-model input for image illustration.

    The selected assistant message remains the visual anchor, but the previous user
    message is included so actions like dancing, rescuing, hugging, swimming or
    kissing are not lost when the assistant reply only reacts to them.

    character_only=True is the contemplative mode: use the context for place/mood,
    but never include the user, persona, crowd, partner, waiter, rescuer or any
    other important visible actor.
    """
    parts = []
    if previous_user_text:
        parts.append("Previous user message:\n" + previous_user_text.strip())
    parts.append("Selected assistant message:\n" + (assistant_text or "").strip())
    if character_only:
        task = (
            "Task:\nCreate a character-only illustration of the selected assistant message. "
            "Show only the main character as the single important visible subject. "
            "Do not include the user, the user persona, a partner, a crowd, a waiter, a rescuer, "
            "or any other secondary actor. Use the previous user message only to preserve the "
            "location, mood, object, or situation when useful."
        )
    else:
        task = (
            "Task:\nBring this scene to life mainly from the selected assistant message, "
            "but include the user's visible action whenever it is part of the moment. "
            + ("The user persona should be visually included as a second adult subject when relevant."
               if include_persona else
               "If the user is physically involved, describe the interaction clearly, even if the user's appearance is generic.")
        )
    parts.append(task)
    return "\n\n".join(parts)


def _krea_scene_fields_from_message(text, settings, previous_user_text="", include_persona=False, character_only=False):
    """Scene planner Krea 2 : JSON strict à 9 champs, interaction-aware.
    Parsing tolérant, jamais d'exception."""
    user_payload = _build_illustration_context(text, previous_user_text, include_persona, character_only) if previous_user_text or include_persona or character_only else text
    messages = [
        {"role": "system", "content": get_effective_krea_scene_planner_prompt()},
        {"role": "user", "content": user_payload},
    ]
    raw = llm_util_chat(messages, settings, max_tokens=500, temperature=0.65)
    return krea_prompt_builder.parse_krea_scene_fields(raw)


def _krea_physical_base(char):
    """Return the persistent physical base used by Krea 2 prompts.

    Character generation historically prepends ``locked_tags`` to ``image_prompt``.
    Joining both fields blindly therefore duplicated the complete physical description.
    Keep the locked traits once, then append only the non-duplicated remainder.
    """
    if not char:
        return ""
    locked = (char.get("locked_tags") or "").strip().strip(",")
    base = (char.get("image_prompt") or "").strip().strip(",")
    if locked and base:
        low_locked = locked.casefold()
        low_base = base.casefold()
        if low_base == low_locked:
            base = ""
        elif low_base.startswith(low_locked):
            base = base[len(locked):].lstrip(" ,;.-")
    return ", ".join(part for part in (locked, base) if part)


def _krea_force_physical(char):
    """Return the per-character physical-description toggle (default: enabled)."""
    if not char:
        return True
    value = char.get("krea_force_physical")
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("0", "false", "off", "no"):
            return False
        if normalized in ("1", "true", "on", "yes"):
            return True
    return bool(value)


def build_krea_chat_prompt(text, settings, char, previous_user_text="", include_persona=False, character_only=False):
    """Prompt Krea 2 pour illustrer un message de conversation : jeton d'identité +
    base physique (si forcée) + scène descriptive littérale issue du planner Krea."""
    fields = _krea_scene_fields_from_message(text, settings, previous_user_text, include_persona, character_only)
    token = (char.get("krea_token") or "").strip() if char else ""
    return krea_prompt_builder.build_krea_prompt(
        fields,
        identity_token=token,
        physical_description=_krea_physical_base(char),
        force_physical=_krea_force_physical(char),
    )


def build_krea_multi_subject_prompt(text, settings, characters, include_persona=False, previous_user_text=""):
    """Build a complete descriptive Krea 2 prompt for duo/group/persona scenes.

    Krea 2's unified local workflow is T2I-only, so every visible subject is described
    explicitly instead of relying on Flux reference-image workflows.
    """
    fields = _krea_scene_fields_from_message(text, settings, previous_user_text, include_persona)
    subjects = []
    for index, char in enumerate(characters or [], 1):
        name = (char.get("name") or f"character {index}").strip()
        token = (char.get("krea_token") or "").strip()
        physical = _krea_physical_base(char) if _krea_force_physical(char) else ""
        pieces = [f"subject {index}", token, name, physical]
        subjects.append(", ".join(piece for piece in pieces if piece))
    if include_persona:
        persona_name = _persona_label(settings)
        persona_token = (settings.get("krea2_user_token") or "").strip()
        persona_description = (settings.get("persona_description") or "").strip()
        pieces = [f"subject {len(subjects) + 1}", persona_token, persona_name, persona_description]
        subjects.append(", ".join(piece for piece in pieces if piece))
    scene = krea_prompt_builder.build_krea_prompt(fields, force_physical=False).rstrip(".")
    count = len(subjects)
    prefix = f"{count} clearly distinct adult subjects" if count > 1 else "one adult subject"
    return prefix + ", " + "; ".join(subjects) + ", " + scene + "."


def _persona_label(settings):
    return (settings.get("persona_name") or "the user").strip() or "the user"


def _persona_ref(settings):
    """Nom de fichier image de la persona si configuree, sinon None."""
    p = (settings.get("persona_image") or "").strip()
    return p or None


def api_generate_in_chat(chat_id, message_id, with_persona=False, prompt=None, dry_run=False):
    """Illustre un message. dry_run=True renvoie seulement le prompt propose (sans generer).
    prompt!=None : utilise ce texte tel quel (corrige par l'utilisateur)."""
    settings = get_settings()
    with db() as c:
        msg = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not msg:
            raise RuntimeError("Message not found.")
        char = c.execute("SELECT * FROM characters WHERE id=?", (msg["character_id"],)).fetchone()
        char = dict(char) if char else None
        prev_user = c.execute(
            "SELECT content FROM messages WHERE chat_id=? AND role='user' AND created_at < ? "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id, msg["created_at"] or 0),
        ).fetchone()
    msg = dict(msg)
    previous_user_text = (prev_user["content"] if prev_user else "") or ""
    avatar = (char.get("avatar") if char else "") or ""
    krea_active = (settings.get("image_family") or "").strip() == "krea2"

    # Determine le mode et le prompt propose
    refs = None
    if krea_active:
        # Global Krea 2 mode: every chat image uses the unified descriptive T2I workflow.
        mode = "krea2"
        if prompt is None:
            if with_persona:
                prompt = build_krea_multi_subject_prompt(
                    msg["content"], settings, [char] if char else [],
                    include_persona=True, previous_user_text=previous_user_text)
            else:
                prompt = build_krea_chat_prompt(
                    msg["content"], settings, char,
                    previous_user_text=previous_user_text,
                    character_only=True)
    elif avatar and with_persona:
        pimg = _persona_ref(settings)
        if pimg:
            mode, refs = "persona", [avatar, pimg]
            if prompt is None:
                names = [char.get("name") or "character", _persona_label(settings)]
                prompt = build_multiref_image_prompt(
                    _build_illustration_context(msg["content"], previous_user_text, include_persona=True),
                    settings, names)
        else:
            # Immersive default without persona image: keep the character reference and
            # let the prompt describe the user generically instead of failing.
            mode = "solo"
            if prompt is None:
                prompt = build_i2i_image_prompt(
                    _build_illustration_context(msg["content"], previous_user_text, include_persona=True),
                    settings)
    elif avatar:
        mode = "solo"
        if prompt is None:
            prompt = build_i2i_image_prompt(msg["content"], settings)
    else:
        mode = "t2i"
        if prompt is None:
            locked = (char.get("locked_tags") or "").strip() if char else ""
            base = (char.get("image_prompt") or "").strip() if char else ""
            hard_locked_identity = ", ".join(p for p in (locked, base) if p)
            prompt = build_t2i_image_prompt(msg["content"], settings, hard_locked_identity)

    if dry_run:
        return {"prompt": prompt, "mode": mode}

    # Conversation LoRA overrides drive the historical Flux stack. Krea 2 has two
    # dedicated slots, so do not consume an "apply once" override that is not applied.
    if krea_active:
        effective_settings, consume_once = settings, False
    else:
        effective_settings, consume_once = _get_chat_lora_settings(chat_id, settings)

    if mode == "persona":
        img, used_seed = generate_group(prompt, refs, effective_settings,
                                        workflow=settings.get("duo_workflow", "duo.json"))
    elif mode == "krea2":
        img, used_seed = generate_t2i(prompt, effective_settings, family="krea2")
    elif mode == "solo":
        img, used_seed = generate_i2i(prompt, avatar, effective_settings)
    else:
        img, used_seed = generate_t2i(prompt, effective_settings)

    # Consommer apply_once si c'était une génération à usage unique
    if consume_once:
        api_chat_lora_clear(chat_id)

    with db() as c:
        c.execute("UPDATE messages SET image=?, image_prompt=?, seed=? WHERE id=?",
                  (img, prompt, used_seed, message_id))
        if char:
            c.execute("UPDATE characters SET last_seed=? WHERE id=?", (used_seed, char["id"]))
            c.execute(
                "INSERT INTO gallery(id, character_id, image, prompt, seed, created_at) VALUES (?,?,?,?,?,?)",
                (new_id(), char["id"], img, prompt, used_seed, time.time()),
            )
    return {"image": img, "prompt": prompt, "seed": used_seed, "with_persona": with_persona}


def api_regenerate_image(message_id, keep_seed=False, prompt=None):
    """Regenere l'image d'un message : meme consigne (ou corrigee), graine conservee ou nouvelle."""
    settings = get_settings()
    with db() as c:
        msg = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not msg:
            raise RuntimeError("Message not found.")
        char = c.execute("SELECT * FROM characters WHERE id=?", (msg["character_id"],)).fetchone()
        char = dict(char) if char else None
        prev_user = c.execute(
            "SELECT content FROM messages WHERE chat_id=? AND role='user' AND created_at < ? "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id, msg["created_at"] or 0),
        ).fetchone()
    msg = dict(msg)
    previous_user_text = (prev_user["content"] if prev_user else "") or ""
    seed = msg.get("seed") if keep_seed else None
    if prompt is None:
        prompt = msg.get("image_prompt") or ""
    avatar = (char.get("avatar") if char else "") or ""
    krea_active = (settings.get("image_family") or "").strip() == "krea2"
    if not prompt:
        # pas de consigne stockee : on recalcule
        if krea_active:
            prompt = build_krea_chat_prompt(msg["content"], settings, char)
        elif avatar:
            prompt = build_i2i_image_prompt(msg["content"], settings)
        else:
            locked = (char.get("locked_tags") or "").strip() if char else ""
            base = (char.get("image_prompt") or "").strip() if char else ""
            hard_locked_identity = ", ".join(p for p in (locked, base) if p)
            prompt = build_t2i_image_prompt(msg["content"], settings, hard_locked_identity)
    if krea_active:
        img, used_seed = generate_t2i(prompt, settings, seed=seed, family="krea2")
    elif avatar:
        img, used_seed = generate_i2i(prompt, avatar, settings, seed=seed)
    else:
        img, used_seed = generate_t2i(prompt, settings, seed=seed)
    with db() as c:
        c.execute("UPDATE messages SET image=?, image_prompt=?, seed=? WHERE id=?",
                  (img, prompt, used_seed, message_id))
        if char:
            c.execute(
                "INSERT INTO gallery(id, character_id, image, prompt, seed, created_at) VALUES (?,?,?,?,?,?)",
                (new_id(), char["id"], img, prompt, used_seed, time.time()),
            )
    return {"image": img, "prompt": prompt, "seed": used_seed}


def api_gallery(character_id=None):
    with db() as c:
        if character_id:
            rows = c.execute("SELECT * FROM gallery WHERE character_id=? ORDER BY created_at DESC",
                             (character_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM gallery ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
#  Memoire des personnages
# --------------------------------------------------------------------------- #
def api_memory_list(character_id):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM memory WHERE character_id=? ORDER BY kind DESC, created_at ASC",
            (character_id,)).fetchall()
    return [dict(r) for r in rows]


def api_memory_add(character_id, kind, content):
    kind = "long" if kind == "long" else "short"
    with db() as c:
        c.execute("INSERT INTO memory(id, character_id, kind, content, created_at) VALUES (?,?,?,?,?)",
                  (new_id(), character_id, kind, content.strip(), time.time()))
    return api_memory_list(character_id)


def api_memory_delete(mem_id):
    with db() as c:
        c.execute("DELETE FROM memory WHERE id=?", (mem_id,))


def api_memory_summarize(character_id, from_chat_id=None):
    """Resume la memoire court terme (ou un chat) en un fait long terme via le LLM."""
    settings = get_settings()
    source = ""
    with db() as c:
        if from_chat_id:
            rows = c.execute(
                "SELECT role, content FROM messages WHERE chat_id=? ORDER BY created_at ASC",
                (from_chat_id,)).fetchall()
            source = "\n".join(f"{r['role']}: {r['content']}" for r in rows)
        else:
            rows = c.execute(
                "SELECT content FROM memory WHERE character_id=? AND kind='short' ORDER BY created_at ASC",
                (character_id,)).fetchall()
            source = "\n".join(r["content"] for r in rows)
    if not source.strip():
        raise RuntimeError("Rien a resumer (memoire court terme vide / conversation vide).")
    messages = [
        {"role": "system", "content":
            "Resume en quelques phrases factuelles, a la 3e personne, les informations durables a "
            "retenir sur ce personnage et sa relation avec l'utilisateur (preferences, evenements "
            "marquants, faits stables). Pas de bavardage, juste les faits a memoriser."},
        {"role": "user", "content": source[:6000]},
    ]
    summary = llm_util_chat(messages, settings, max_tokens=300, temperature=0.4)
    with db() as c:
        c.execute("INSERT INTO memory(id, character_id, kind, content, created_at) VALUES (?,?,?,?,?)",
                  (new_id(), character_id, "long", summary.strip(), time.time()))
    return {"summary": summary.strip()}


# --------------------------------------------------------------------------- #
#  Avatar : options (reroll / keep seed / variantes / definir principal)
# --------------------------------------------------------------------------- #
VARIANT_TAGS = {
    "expression_sourire": "smiling, happy expression",
    "expression_serieux": "serious expression",
    "expression_colere": "angry expression",
    "expression_triste": "sad expression",
    "expression_surprise": "surprised expression",
    "tenue_casual": "casual outfit",
    "tenue_elegante": "elegant dress",
    "tenue_sport": "sportswear",
    "tenue_plage": "swimsuit, beach",
    "tenue_hiver": "winter clothes, coat",
    "fond_studio": "plain studio background",
    "fond_exterieur": "outdoor background, nature",
    "fond_ville": "city street background",
    "fond_chambre": "bedroom background",
    "fond_nuit": "night background, city lights",
}

# Les 10 émotions du portrait dynamique. Pour chaque: instruction visuelle (injectée dans le prompt I2I)
EMOTIONS = {
    "happy":    "exaggeratedly happy, broad genuine smile, bright wide eyes, lifted cheeks, joyful energetic expression",
    "calm":     "deeply relaxed, peaceful eyes, soft natural smile, serene expression",
    "playful":  "mischievous grin, teasing gaze, raised eyebrow, confident playful expression",
    "shy":      "intensely shy, averted gaze, blushing cheeks, nervous soft smile, visibly embarrassed",
    "sad":      "visibly devastated, watery downcast eyes, trembling lower lip, heavy expression, emotionally exhausted face",
    "angry":    "exaggeratedly angry, deeply furrowed brows, narrowed intense eyes, clenched jaw, tense facial muscles, direct hostile stare",
    "tired":    "obviously exhausted, heavy eyelids, drained expression, subtle eye bags, low energy posture",
    "excited":  "visibly thrilled, wide sparkling eyes, big energetic smile, animated expression",
    "romantic": "openly romantic, soft loving gaze, warm smile, slightly flushed cheeks, intimate affectionate expression",
    "cold":     "emotionally distant, blank controlled expression, icy stare, closed-off posture",
}

# Mapping mood calculé → émotion portrait (quand l'humeur change, quel portrait afficher)
MOOD_TO_EMOTION = {
    "playful": "playful", "calm": "calm", "tired": "tired", "distant": "cold",
    "anxious": "sad", "excited": "excited", "warm": "romantic", "cheerful": "happy",
    "relaxed": "calm", "neutral": "calm",
}

# Influence du ton LLM par émotion (injectée dans le system prompt)
EMOTION_TONE = {
    "happy":    "You are joyful and radiant — smile in the words, lightness, enthusiasm.",
    "calm":     "You are calm and serene — soft measured sentences, kind tone.",
    "playful":  "You are playful and teasing — light provocations, soft humor, easy laughter.",
    "shy":      "You are shy and slightly modest — hesitations, carefully chosen words, tendency to downplay.",
    "sad":      "You are melancholic and introspective — shorter replies, soft but veiled tone.",
    "angry":    "You are irritated — direct dry replies, short sentences. You contain your anger, but it shows through.",
    "tired":    "You are tired — brief replies, less enthusiasm, and you struggle a little to keep up.",
    "excited":  "You are very expressive and enthusiastic — overflowing curiosity, exclamations, energy.",
    "romantic": "You are tender and affectionate — soft words, emotional closeness, warm intimate tone.",
    "cold":     "You are distant and reserved — sober replies, little initiative, minimal tone.",
}


def get_char_emotions(character_id):
    """Renvoie {emotion: image} pour un personnage."""
    with db() as c:
        rows = c.execute("SELECT emotion, image FROM char_emotions WHERE character_id=?",
                         (character_id,)).fetchall()
    return {r["emotion"]: r["image"] for r in rows}


def api_generate_emotion_portrait(character_id, emotion, dry_run=False, prompt=None):
    """Generate an emotion portrait using the globally selected image engine."""
    if emotion not in EMOTIONS:
        raise RuntimeError(f"Unknown emotion: {emotion}")
    settings = get_settings()
    with db() as c:
        char = c.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
    if not char:
        raise RuntimeError("Character not found.")
    char = dict(char)
    krea_active = (settings.get("image_family") or "").strip() == "krea2"
    avatar = (char.get("avatar") or "").strip()
    if not krea_active and not avatar:
        raise RuntimeError("This character does not have a main avatar yet. Generate it first.")
    if prompt is None:
        emotion_hint = EMOTIONS[emotion]
        if krea_active:
            fields = {
                "framing": "close-up portrait, face centered, eye-level camera",
                "pose_action": "head and shoulders visible in a natural still pose",
                "expression": emotion_hint + ", unmistakable exaggerated facial expression",
                "outfit": "simple everyday clothing",
                "environment": "clean neutral portrait background",
                "weather": "",
                "lighting": "soft balanced portrait lighting",
                "mood": f"clear {emotion} emotional portrait",
                "style_traits": "photorealistic detail, natural skin texture, sharp facial features",
            }
            prompt = krea_prompt_builder.build_krea_prompt(
                fields,
                identity_token=(char.get("krea_token") or "").strip(),
                physical_description=_krea_physical_base(char),
                force_physical=_krea_force_physical(char),
            )
        else:
            prompt = (
                "Make a close-up portrait of this exact character. Preserve the same identity, "
                "facial features, hairstyle, skin tone, body proportions and visual style as the "
                "reference image. The emotion must be unmistakable, deliberately exaggerated and "
                "readable at a glance. The facial expression is the main focus. Never make the "
                f"expression subtle, neutral or ambiguous. {emotion_hint}."
            )
    if dry_run:
        return {"prompt": prompt, "emotion": emotion}
    if krea_active:
        img, used_seed = generate_t2i(prompt, settings, family="krea2")
    else:
        img, used_seed = generate_i2i(prompt, avatar, settings)
    with db() as c:
        c.execute("INSERT OR REPLACE INTO char_emotions(character_id, emotion, image, created_at) "
                  "VALUES (?,?,?,?)", (character_id, emotion, img, time.time()))
    return {"emotion": emotion, "image": img, "seed": used_seed}


# --------------------------------------------------------------------------- #
#  Scénarios
# --------------------------------------------------------------------------- #
SCENARIO_PLACES = [
    "apartment", "club", "beach", "school", "office", "dream",
    "storm", "night", "date", "mystery", "comfort", "drama",
    "forest", "cafe", "hospital", "hotel", "rooftop", "library",
]

SCENARIO_MOODS = ["romantic", "tense", "playful", "melancholic", "mysterious",
                   "cozy", "dangerous", "euphoric", "calm", "dramatic"]

SCENARIO_THEMES = ["betrayal", "reunion", "first_meeting", "goodbye", "discovery",
                    "confession", "rescue", "rivalry", "healing", "seduction"]

SCENARIO_RELATIONSHIPS = ["strangers", "lovers", "exes", "friends", "rivals",
                           "colleagues", "enemies", "mentor_student", "siblings", "boss_employee"]


def api_scenario_list():
    with db() as c:
        rows = c.execute("SELECT * FROM scenarios ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def api_scenario_save(data):
    sid = data.get("id") or new_id()
    with db() as c:
        exists = c.execute("SELECT 1 FROM scenarios WHERE id=?", (sid,)).fetchone()
        fields = ("title", "place", "mood_theme", "theme", "relationship", "goal", "conflict", "notes")
        vals = {k: (data.get(k) or "") for k in fields}
        if exists:
            c.execute(
                "UPDATE scenarios SET title=?,place=?,mood_theme=?,theme=?,relationship=?,goal=?,conflict=?,notes=? WHERE id=?",
                (*[vals[k] for k in fields], sid))
        else:
            c.execute(
                "INSERT INTO scenarios(id,title,place,mood_theme,theme,relationship,goal,conflict,notes,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, *[vals[k] for k in fields], time.time()))
    return {"id": sid, **vals}


def api_scenario_delete(sid):
    with db() as c:
        c.execute("DELETE FROM scenarios WHERE id=?", (sid,))
    return {"ok": True}


# --------------------------------------------------------------------------- #
#  Journal / Timeline
# --------------------------------------------------------------------------- #
JOURNAL_KINDS = ("moment", "first_meeting", "favorite", "saved_image", "memory_event")


def api_journal_list(character_id=None):
    with db() as c:
        if character_id:
            rows = c.execute(
                "SELECT * FROM journal WHERE character_id=? OR character_id IS NULL "
                "ORDER BY pinned DESC, date DESC, created_at DESC", (character_id,)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM journal ORDER BY pinned DESC, date DESC, created_at DESC").fetchall()
    return [dict(r) for r in rows]


def api_journal_add(character_id, kind, title, content, image="", date=None, pinned=0):
    import datetime
    if kind not in JOURNAL_KINDS:
        kind = "moment"
    if not date:
        date = datetime.date.today().isoformat()
    jid = new_id()
    with db() as c:
        c.execute("INSERT INTO journal(id, character_id, kind, title, content, image, date, created_at, pinned) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (jid, character_id or None, kind, title or "", content or "", image or "",
                   date, time.time(), 1 if pinned else 0))
    return {"id": jid, "kind": kind, "date": date}


def api_journal_delete(jid):
    with db() as c:
        c.execute("DELETE FROM journal WHERE id=?", (jid,))
    return {"ok": True}


def api_journal_pin(jid, pinned):
    with db() as c:
        c.execute("UPDATE journal SET pinned=? WHERE id=?", (1 if pinned else 0, jid))
    return {"ok": True}


def api_journal_generate(character_id, settings):
    """Génère une entrée de timeline à partir de l'historique récent du personnage (via LLM)."""
    with db() as c:
        rows = c.execute(
            "SELECT m.role, m.content FROM messages m "
            "JOIN chat_members cm ON cm.chat_id = m.chat_id "
            "WHERE cm.character_id=? ORDER BY m.created_at DESC LIMIT 12", (character_id,)).fetchall()
        char = c.execute("SELECT name FROM characters WHERE id=?", (character_id,)).fetchone()
    if not rows:
        raise RuntimeError("No conversation yet to generate a moment.")
    name = char["name"] if char else "The character"
    excerpt = "\n".join(f"[{r['role']}] {(r['content'] or '')[:150]}" for r in reversed(rows))
    sysmsg = ("Summarize this relationship moment as ONE journal sentence, in third person, "
              f"like a timeline entry (example: '{name} learned that the user likes "
              "soft and playful conversations.'). Reply with only the sentence, nothing else.")
    event = llm_util_chat([{"role": "system", "content": sysmsg},
                      {"role": "user", "content": excerpt}], settings,
                     max_tokens=80, temperature=0.7).strip().strip('"')
    return api_journal_add(character_id, "memory_event", "", event)


# --------------------------------------------------------------------------- #
#  LoRA — pile active + bibliothèque + presets
#
#  ARCHITECTURE v14 :
#  - table `loras` : pile ACTIVE (LoRA configurées pour être injectées).
#    Colonnes : id, file, trigger, strength, clip_strength, always_on, family, note,
#               favorite, created_at.
#  - table `lora_presets` : presets nommés (Étape 4).
#    Colonnes : id, name, family, context (character/workflow/global), context_id, stack (JSON), created_at.
#  - /api/loras         GET  → liste la pile active
#  - /api/lora/save     POST → ajoute ou édite une entrée de la pile active
#  - /api/lora/delete   POST → supprime de la pile active
#  - /api/lora/toggle   POST → active / désactive (always_on) sans supprimer
#  - /api/lora/favorite POST → marque / démarque un favori
#  - /api/lora/library  GET  → LoRA détectées dans le catalogue (kind=lora), enrichies
#  - /api/lora/presets  GET  → liste les presets (Étape 4, données prêtes)
#  - /api/lora/preset/save   POST → sauvegarde un preset
#  - /api/lora/preset/delete POST → supprime un preset
#  - /api/lora/preset/apply  POST → charge un preset dans la pile active
# --------------------------------------------------------------------------- #

# Familles qui supportent CLIP strength (encodeur texte séparé)
_LORA_CLIP_FAMILIES = {"sd15", "sdxl", "flux", "flux2_klein"}


def _lora_compatible(lo_family, wf_family):
    """True si la LoRA est compatible avec la famille de workflow.
    Une LoRA sans famille détectée (None/'') est acceptée partout (conservatif)."""
    if not lo_family:
        return True  # unknown -> non bloquant, avertissement seulement
    if not wf_family:
        return True
    return lo_family == wf_family


def api_lora_list():
    """Pile active : toutes les LoRA configurées, ordonnées par created_at."""
    with db() as c:
        rows = c.execute("SELECT * FROM loras ORDER BY created_at ASC").fetchall()
    return [dict(r) for r in rows]


def _sync_loras_to_settings():
    """Recopie la table loras dans le réglage 'loras' (JSON) lu par engine._inject_loras.
    Rétrocompatible : engine.py lit {file, trigger, strength, always}."""
    rows = api_lora_list()
    payload = [
        {
            "file":     r["file"],
            "trigger":  r["trigger"] or "",
            "strength": r["strength"],
            "always":   bool(r["always_on"]),
        }
        for r in rows
    ]
    save_settings({"loras": json.dumps(payload, ensure_ascii=False)})


def api_lora_save(data):
    """Ajoute ou édite une entrée dans la pile active."""
    lid = data.get("id") or new_id()
    with db() as c:
        exists = c.execute("SELECT 1 FROM loras WHERE id=?", (lid,)).fetchone()
        vals = (
            data.get("file", ""),
            data.get("trigger", ""),
            float(data.get("strength", 0.8) or 0.8),
            float(data.get("clip_strength", 1.0) or 1.0),
            1 if data.get("always_on") else 0,
            (data.get("family") or "").strip() or None,
            data.get("note", ""),
            1 if data.get("favorite") else 0,
        )
        if exists:
            c.execute(
                "UPDATE loras SET file=?, trigger=?, strength=?, clip_strength=?, "
                "always_on=?, family=?, note=?, favorite=? WHERE id=?",
                (*vals, lid),
            )
        else:
            c.execute(
                "INSERT INTO loras(id, file, trigger, strength, clip_strength, always_on, "
                "family, note, favorite, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (lid, *vals, time.time()),
            )
    _sync_loras_to_settings()
    return {"id": lid}


def api_lora_delete(lid):
    with db() as c:
        c.execute("DELETE FROM loras WHERE id=?", (lid,))
    _sync_loras_to_settings()
    return {"ok": True}


def api_lora_toggle(lid, always_on):
    """Active/désactive le mode 'toujours actif' sans supprimer."""
    with db() as c:
        c.execute("UPDATE loras SET always_on=? WHERE id=?", (1 if always_on else 0, lid))
    _sync_loras_to_settings()
    return {"ok": True}


def api_lora_favorite(lid, favorite):
    """Marque ou démarque un favori."""
    with db() as c:
        c.execute("UPDATE loras SET favorite=? WHERE id=?", (1 if favorite else 0, lid))
    return {"ok": True}


def api_lora_library(family=None, search=None, favorites_only=False, preview_filter=None):
    """Retourne les LoRA détectées dans le catalogue de modèles (kind='lora'),
    enrichies avec leur statut dans la pile active et leur preview si disponible.
    preview_filter : None = toutes | 'with' = avec preview | 'without' = sans preview."""
    query = (
        "SELECT mf.*, mfo.path AS folder_path FROM model_files mf "
        "JOIN model_folders mfo ON mfo.id = mf.folder_id "
        "WHERE mf.kind='lora' AND mfo.enabled=1 AND mf.missing=0"
    )
    params = []
    if family:
        query += " AND mf.family=?"
        params.append(family)
    query += " ORDER BY mf.name COLLATE NOCASE ASC"

    with db() as c:
        catalog_rows = c.execute(query, params).fetchall()
        active_rows  = c.execute("SELECT * FROM loras").fetchall()
        preview_rows = c.execute("SELECT * FROM lora_previews").fetchall()

    active_by_file  = {r["file"]: dict(r) for r in active_rows}
    preview_by_name = {r["lora_name"]: dict(r) for r in preview_rows}

    out = []
    for r in catalog_rows:
        d = dict(r)
        d["size_human"]  = model_catalog.format_size(d.get("size"))
        folder_p = d.get("folder_path", "")
        d["folder_short"] = os.path.basename(folder_p.rstrip(os.sep)) if folder_p else "?"
        act = active_by_file.get(d["name"])
        d["in_stack"]   = bool(act)
        d["stack_entry"] = act
        prv = preview_by_name.get(d["name"])
        d["preview"]    = prv  # None si pas de preview
        if favorites_only and not (act and act.get("favorite")):
            continue
        if search and search.lower() not in d["name"].lower():
            continue
        if preview_filter == "with" and not prv:
            continue
        if preview_filter == "without" and prv:
            continue
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
#  Étape 4 — Presets LoRA (structure prête, API minimale opérationnelle)
# --------------------------------------------------------------------------- #

def api_lora_presets_list(context=None, context_id=None, family=None):
    query = "SELECT * FROM lora_presets WHERE 1=1"
    params = []
    if context:
        query += " AND context=?"; params.append(context)
    if context_id:
        query += " AND context_id=?"; params.append(context_id)
    if family:
        query += " AND family=?"; params.append(family)
    query += " ORDER BY created_at DESC"
    with db() as c:
        rows = c.execute(query, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["stack"] = json.loads(d.get("stack") or "[]")
        except Exception:
            d["stack"] = []
        out.append(d)
    return out


def api_lora_preset_save(data):
    pid = data.get("id") or new_id()
    stack = data.get("stack", [])
    if not isinstance(stack, list):
        stack = []
    with db() as c:
        exists = c.execute("SELECT 1 FROM lora_presets WHERE id=?", (pid,)).fetchone()
        vals = (
            (data.get("name") or "Preset").strip(),
            (data.get("family") or "").strip() or None,
            (data.get("context") or "global").strip(),
            (data.get("context_id") or "").strip() or None,
            json.dumps(stack, ensure_ascii=False),
        )
        if exists:
            c.execute(
                "UPDATE lora_presets SET name=?, family=?, context=?, context_id=?, stack=? WHERE id=?",
                (*vals, pid),
            )
        else:
            c.execute(
                "INSERT INTO lora_presets(id, name, family, context, context_id, stack, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (pid, *vals, time.time()),
            )
    return {"id": pid}


def api_lora_preset_delete(pid):
    with db() as c:
        c.execute("DELETE FROM lora_presets WHERE id=?", (pid,))
    return {"ok": True}


def api_lora_preset_apply(pid):
    """Remplace la pile active par le contenu d'un preset."""
    with db() as c:
        row = c.execute("SELECT * FROM lora_presets WHERE id=?", (pid,)).fetchone()
    if not row:
        raise RuntimeError("Preset not found.")
    try:
        stack = json.loads(row["stack"] or "[]")
    except Exception:
        stack = []
    # Vider la pile active et remplacer
    with db() as c:
        c.execute("DELETE FROM loras")
    for entry in stack:
        api_lora_save(entry)
    return {"ok": True, "count": len(stack)}


def api_lora_workflow_compat(wf_name):
    """Vérifie si un workflow déclare un slot LoRA natif.
    Retourne supports_lora, le slot s'il existe, et un message clair si non."""
    manifest  = model_manifests.get_workflow_manifest(wf_name) if wf_name else None
    lora_decl = model_manifests.get_lora_slot_info_from_manifest(manifest) if manifest else None
    loras_raw = get_settings().get("loras", "[]")
    try:
        active_count = len([lo for lo in json.loads(loras_raw)
                           if lo.get("always") or lo.get("trigger")])
    except Exception:
        active_count = 0
    return {
        "wf_name":       wf_name,
        "supports_lora": bool(lora_decl),
        "lora_slot":     lora_decl,
        "active_loras":  active_count,
        "message":       None if lora_decl else (
            "This workflow does not declare a LoRA slot yet. "
            "Generation will run without LoRA."
            if active_count > 0 else None
        ),
    }


# --------------------------------------------------------------------------- #
#  LoRA Previews — stockage, génération, assignation
# --------------------------------------------------------------------------- #

LORA_PREVIEW_DEFAULT_PROMPT = (
    "A clear high-quality portrait of a person, centered composition, upper body, "
    "neutral pose, looking at the camera, simple background, balanced lighting."
)

# Mapping famille → workflow preview préféré (doit avoir supports_lora=True)
_LORA_PREVIEW_WORKFLOWS = {
    "flux2_klein": "preview.json",
    "flux":        "preview.json",
    "krea2":       model_manifests.KREA2_WORKFLOW,   # même workflow unifié, réglages allégés
    # sdxl / sd15 / zimage : à étendre quand leurs workflows auront un slot LoRA
}


def _lora_preview_workflow_for_family(family):
    """Retourne le nom du workflow preview pour cette famille, ou None si non disponible."""
    return _LORA_PREVIEW_WORKFLOWS.get(family or "flux2_klein")


def api_lora_preview_get(lora_name):
    """Retourne la preview enregistrée pour une LoRA, ou None."""
    with db() as c:
        row = c.execute("SELECT * FROM lora_previews WHERE lora_name=?", (lora_name,)).fetchone()
    return dict(row) if row else None


def api_lora_previews_list():
    """Retourne toutes les previews enregistrées, indexées par lora_name."""
    with db() as c:
        rows = c.execute("SELECT * FROM lora_previews ORDER BY updated_at DESC").fetchall()
    return {r["lora_name"]: dict(r) for r in rows}


def _krea_preview_settings(settings, clear_loras=False):
    """Build isolated Krea preview settings without mutating global settings.

    Turbo/distilled checkpoints use the reduced preview step count. RAW keeps its safe
    profile because forcing a few-step RAW preview gives misleadingly poor results.
    """
    preview = dict(settings)
    model_name = (preview.get("krea2_unet") or "").strip().lower()
    is_raw = "raw" in model_name and "turbo" not in model_name
    if is_raw:
        preview["krea2_sampler_profile"] = "raw"
    else:
        preview["krea2_sampler_profile"] = "custom"
        preview["krea2_steps"] = settings.get("krea2_preview_steps", "6")
        if "turbo" in model_name or "distill" in model_name:
            preview["krea2_cfg"] = "1.0"
    preview["image_resolution"] = "512x512"
    if clear_loras:
        preview["krea2_char_lora"] = ""
        preview["krea2_util_lora"] = ""
    return preview


def api_lora_preview_generate(lora_name, family=None, prompt=None, negative=None, seed=None):
    """Génère une image de preview pour une LoRA de façon ISOLÉE :
    - n'affecte pas la pile LoRA globale ;
    - n'affecte pas Studio Image ;
    - utilise le workflow preview dédié de la famille.
    Retourne {image, seed, workflow_used, prompt_used}.
    """
    settings = get_settings()

    # 1. Choisir le workflow preview
    eff_family = (family or "flux2_klein").strip()
    wf_name    = _lora_preview_workflow_for_family(eff_family)
    if not wf_name:
        raise RuntimeError(
            f"No compatible preview workflow is configured for family '{eff_family}'. "
            f"Available families: {', '.join(_LORA_PREVIEW_WORKFLOWS)}."
        )

    # 2. Vérifier que le workflow a un slot LoRA
    manifest  = model_manifests.get_workflow_manifest(wf_name)
    lora_decl = model_manifests.get_lora_slot_info_from_manifest(manifest)
    if not lora_decl:
        raise RuntimeError(
            f"The preview workflow '{wf_name}' does not declare a LoRA slot. "
            f"This LoRA cannot be injected for preview."
        )

    # 3. Vérifier que la LoRA est connue de ComfyUI
    known_loras = comfy_list_loras(settings)
    from engine import _resolve_lora_name
    resolved = _resolve_lora_name(lora_name, known_loras) if known_loras else lora_name
    if known_loras and resolved is None:
        raise RuntimeError(
            f"LoRA '{lora_name}' was not found in ComfyUI "
            f"(list of {len(known_loras)} known LoRAs). "
            f"Make sure it is present in ComfyUI models/loras/."
        )

    eff_prompt = (prompt or LORA_PREVIEW_DEFAULT_PROMPT).strip()
    eff_neg    = (negative or settings.get("default_negative", "")).strip()

    # 4. Génération isolée : injection temporaire de la LoRA dans un settings éphémère
    # On crée un dict settings local avec UNIQUEMENT cette LoRA — pas de contamination de la pile globale.
    preview_settings = dict(settings)
    if eff_family == "krea2":
        # Krea 2 uses its dedicated character slot; the utility slot stays isolated.
        preview_settings = _krea_preview_settings(settings)
        preview_settings["krea2_char_lora"] = resolved
        preview_settings["krea2_char_lora_strength"] = "0.8"
        preview_settings["krea2_util_lora"] = ""
    else:
        preview_settings["loras"] = json.dumps([{
            "file":          resolved,
            "trigger":       "",
            "strength":      0.8,
            "clip_strength": 1.0,
            "always":        True,
            "family":        eff_family,
        }])
    # Forcer la famille pour que _inject_models_for_family utilise les bons modèles
    preview_settings["image_family"] = eff_family

    img, used_seed = generate_t2i(
        eff_prompt, preview_settings,
        negative=eff_neg,
        seed=seed,
        workflow=wf_name,
        family=eff_family,
    )

    # 5. Sauvegarder comme preview de cette LoRA
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO lora_previews"
            "(lora_name, family, preview_path, preview_source, prompt_used, "
            " workflow_used, seed, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (lora_name, eff_family, img, "generated", eff_prompt, wf_name, used_seed, time.time()),
        )
    return {"image": img, "seed": used_seed, "workflow_used": wf_name,
            "prompt_used": eff_prompt, "lora_name": lora_name}


def api_lora_preview_assign(lora_name, family=None, source="selected_gallery", image=None,
                            image_b64=None, image_filename=None):
    """Assigne une image existante ou importée comme preview d'une LoRA.
    source = 'selected_gallery' : image est un nom de fichier déjà dans data/images/
    source = 'imported_file'    : image_b64 est le contenu base64 d'un fichier importé
    """
    if not lora_name:
        raise RuntimeError("lora_name manquant.")

    if source == "selected_gallery":
        if not image:
            raise RuntimeError("Nom d'image manquant pour l'assignation depuis la galerie.")
        # Only gallery basenames are accepted; never allow relative path traversal.
        raw_image = str(image).replace("\\", "/")
        safe_image = os.path.basename(raw_image)
        if not safe_image or raw_image != safe_image:
            raise RuntimeError("Invalid gallery image name.")
        img_path = os.path.join(IMG_DIR, safe_image)
        if not os.path.isfile(img_path):
            raise RuntimeError(f"Image '{safe_image}' not found in the AmiorAI gallery.")
        final_image = safe_image

    elif source == "imported_file":
        if not image_b64:
            raise RuntimeError("Missing image data for import.")
        try:
            import base64
            raw = base64.b64decode(image_b64)
        except Exception as e:
            raise RuntimeError(f"Invalid image (base64 decoding error): {e}")
        # Confirm que c'est bien une image (magic bytes PNG ou JPEG)
        if not (raw[:8] == b'\x89PNG\r\n\x1a\n' or raw[:2] == b'\xff\xd8'):
            raise RuntimeError("Image invalide pour la preview (format non reconnu — PNG ou JPEG attendu).")
        ext  = ".png" if raw[:8] == b'\x89PNG\r\n\x1a\n' else ".jpg"
        fname = f"lora_preview_{new_id()}{ext}"
        with open(os.path.join(IMG_DIR, fname), "wb") as fh:
            fh.write(raw)
        final_image = fname

    else:
        raise RuntimeError(f"Source unknowne : '{source}'.")

    eff_family = (family or "").strip() or None
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO lora_previews"
            "(lora_name, family, preview_path, preview_source, prompt_used, "
            " workflow_used, seed, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (lora_name, eff_family, final_image, source, None, None, None, time.time()),
        )
    return {"ok": True, "image": final_image, "lora_name": lora_name}


def api_lora_preview_delete(lora_name):
    """Supprime la preview enregistrée pour une LoRA (ne supprime pas l'image physique)."""
    with db() as c:
        c.execute("DELETE FROM lora_previews WHERE lora_name=?", (lora_name,))
    return {"ok": True}


# --------------------------------------------------------------------------- #
#  Sélection LoRA par conversation
#  Permet d'attacher jusqu'à 2 LoRA à une conversation spécifique,
#  indépendamment de la pile globale du LoRA Manager.
# --------------------------------------------------------------------------- #

def api_chat_lora_get(chat_id: str) -> dict:
    """Retourne la sélection LoRA active pour cette conversation."""
    with db() as c:
        row = c.execute("SELECT * FROM chat_lora_selection WHERE chat_id=?",
                        (chat_id,)).fetchone()
    if not row:
        return {"chat_id": chat_id, "primary": None, "secondary": None, "apply_once": False}
    d = dict(row)
    primary = None
    if d.get("primary_lora_file"):
        primary = {"file": d["primary_lora_file"], "strength": d["primary_strength"],
                   "clip_strength": d["primary_clip_str"]}
    secondary = None
    if d.get("secondary_lora_file"):
        secondary = {"file": d["secondary_lora_file"], "strength": d["secondary_strength"],
                     "clip_strength": d["secondary_clip_str"]}
    return {"chat_id": chat_id, "primary": primary, "secondary": secondary,
            "apply_once": bool(d.get("apply_once"))}


def api_chat_lora_set(chat_id: str, primary: dict | None, secondary: dict | None,
                      apply_once: bool = False) -> dict:
    """Définit ou met à jour la sélection LoRA pour cette conversation.
    Limite stricte : 2 LoRA maximum. Les doublons (même fichier) sont refusés."""
    # Validation
    pf = (primary or {}).get("file", "").strip() if primary else ""
    sf = (secondary or {}).get("file", "").strip() if secondary else ""
    if pf and sf and pf == sf:
        raise RuntimeError("The two slots cannot contain the same LoRA.")
    # Blocage par hash SHA256 (même fichier sous deux noms différents)
    if pf and sf and pf != sf:
        with db() as _c:
            h_p = _c.execute("SELECT file_hash FROM lora_civitai_metadata "
                             "JOIN model_files ON model_files.id=model_file_id "
                             "WHERE model_files.name=? AND file_hash IS NOT NULL", (pf,)).fetchone()
            h_s = _c.execute("SELECT file_hash FROM lora_civitai_metadata "
                             "JOIN model_files ON model_files.id=model_file_id "
                             "WHERE model_files.name=? AND file_hash IS NOT NULL", (sf,)).fetchone()
        if h_p and h_s and h_p[0] == h_s[0]:
            raise RuntimeError(
                "These two LoRAs are identical copies (same SHA256 hash). "
                "Only one copy can be used per generation.")
    with db() as c:
        c.execute(
            "INSERT INTO chat_lora_selection(chat_id, primary_lora_file, primary_strength, "
            "primary_clip_str, secondary_lora_file, secondary_strength, secondary_clip_str, "
            "apply_once, updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "primary_lora_file=excluded.primary_lora_file, "
            "primary_strength=excluded.primary_strength, "
            "primary_clip_str=excluded.primary_clip_str, "
            "secondary_lora_file=excluded.secondary_lora_file, "
            "secondary_strength=excluded.secondary_strength, "
            "secondary_clip_str=excluded.secondary_clip_str, "
            "apply_once=excluded.apply_once, updated_at=excluded.updated_at",
            (chat_id, pf or None, float((primary or {}).get("strength", 0.8)),
             float((primary or {}).get("clip_strength", 1.0)),
             sf or None, float((secondary or {}).get("strength", 0.8)),
             float((secondary or {}).get("clip_strength", 1.0)),
             1 if apply_once else 0, time.time()),
        )
    return api_chat_lora_get(chat_id)


def api_chat_lora_clear(chat_id: str) -> dict:
    """Efface la sélection LoRA pour cette conversation."""
    with db() as c:
        c.execute("DELETE FROM chat_lora_selection WHERE chat_id=?", (chat_id,))
    return {"chat_id": chat_id, "primary": None, "secondary": None, "apply_once": False}


def _get_chat_lora_settings(chat_id: str, base_settings: dict) -> dict:
    """Construit les settings effectifs pour une génération image de conversation.
    La sélection LoRA de la conversation override la pile globale.
    Retourne aussi consume_apply_once=True si le flag doit être consumé."""
    sel = api_chat_lora_get(chat_id)
    active = []
    if sel.get("primary"):
        p = sel["primary"]
        active.append({"file": p["file"], "trigger": "", "strength": p["strength"],
                       "clip_strength": p["clip_strength"], "always": True, "family": ""})
    if sel.get("secondary"):
        s = sel["secondary"]
        active.append({"file": s["file"], "trigger": "", "strength": s["strength"],
                       "clip_strength": s["clip_strength"], "always": True, "family": ""})
    if not active:
        # Pas de sélection conversation → utiliser la pile globale
        return dict(base_settings), False
    # Override : remplacer la pile globale par la sélection conversation (max 2)
    effective = dict(base_settings)
    effective["loras"] = json.dumps(active[:2], ensure_ascii=False)
    return effective, bool(sel.get("apply_once"))


# --------------------------------------------------------------------------- #
#  CIVITAI — Token sécurisé + identification par hash + cache previews
#
#  Stockage du token :
#    Windows  : keyring (Credential Manager / DPAPI via backend Windows)
#    Linux/Mac: keyring si disponible (SecretService / Keychain), sinon fichier
#               chiffré AES en mémoire de session avec avertissement.
#    Le token n'est JAMAIS renvoyé au frontend après enregistrement.
#    Il n'est JAMAIS écrit dans les logs, les exports ou settings.json.
#
#  Dossier cache previews Civitai : data/lora_previews/civitai/
#
#  Table lora_civitai_metadata :
#    Liée à model_file_id (clé stable de model_files). Clé = model_file_id
#    afin d'éviter les collisions si deux dossiers contiennent un fichier du
#    même nom.
# --------------------------------------------------------------------------- #

CIVITAI_CACHE_DIR = os.path.join(DATA_DIR, "lora_previews", "civitai")
os.makedirs(CIVITAI_CACHE_DIR, exist_ok=True)

_CIVITAI_TOKEN_SERVICE = "AmiorAI"
_CIVITAI_TOKEN_USER    = "civitai_api_token"

# Slot de session pour les plateformes sans keyring disponible (avertissement affiché)
_civitai_session_token: str = ""
_civitai_keyring_available: bool = False

try:
    import keyring  # type: ignore
    _civitai_keyring_available = True
    log.info("[Civitai] keyring available — secure storage enabled")
except ImportError:
    log.warning("[Civitai] keyring missing — the token will be stored in session memory only. "
                "Install 'keyring' with pip for persistent storage.")


def _civitai_save_token(token: str) -> str:
    """Sauvegarde le token de façon sécurisée. Retourne 'keyring' ou 'session'."""
    global _civitai_session_token
    token = (token or "").strip()
    if not token:
        raise RuntimeError("Empty token — canceled.")
    if _civitai_keyring_available:
        keyring.set_password(_CIVITAI_TOKEN_SERVICE, _CIVITAI_TOKEN_USER, token)
        _civitai_session_token = ""
        return "keyring"
    else:
        _civitai_session_token = token
        return "session"


def _civitai_get_token() -> str:
    """Retourne le token en mémoire. Ne log jamais son contenu."""
    if _civitai_keyring_available:
        try:
            t = keyring.get_password(_CIVITAI_TOKEN_SERVICE, _CIVITAI_TOKEN_USER)
            return t or ""
        except Exception:
            return ""
    return _civitai_session_token


def _civitai_delete_token():
    """Supprime le token du stockage sécurisé."""
    global _civitai_session_token
    _civitai_session_token = ""
    if _civitai_keyring_available:
        try:
            keyring.delete_password(_CIVITAI_TOKEN_SERVICE, _CIVITAI_TOKEN_USER)
        except Exception:
            pass


def _civitai_token_status() -> dict:
    """Retourne le statut du token sans jamais exposer sa valeur."""
    token = _civitai_get_token()
    return {
        "configured": bool(token),
        "storage":    "keyring" if _civitai_keyring_available else "session",
        "keyring_available": _civitai_keyring_available,
        "warning": (None if _civitai_keyring_available else
                    "keyring missing: the token is stored in session memory and will be lost on restart. "
                    "Install 'keyring' with pip to keep it."),
    }


def _civitai_request(endpoint: str, params: dict = None) -> dict:
    """Effectue un appel GET à l'API Civitai. Lance RuntimeError si échec."""
    token = _civitai_get_token()
    base  = "https://civitai.com/api/v1"
    url   = base + endpoint
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={
        "User-Agent":    "AmiorAI/1.0",
        "Accept":        "application/json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 401:
                raise RuntimeError("Invalid or expired Civitai token (401).")
            if resp.status == 429:
                raise RuntimeError("Civitai is temporarily rate-limiting requests. Try again later (429).")
            if resp.status != 200:
                raise RuntimeError(f"Civitai returned {resp.status}.")
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("Invalid or expired Civitai token (401).")
        if e.code == 429:
            raise RuntimeError("Civitai is temporarily rate-limiting requests (429).")
        raise RuntimeError(f"Civitai HTTP error: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Civitai network error: {e.reason}")


def api_civitai_token_save(token: str) -> dict:
    storage = _civitai_save_token(token)
    st = _civitai_token_status()
    return {"ok": True, "storage": storage, **st}


def api_civitai_token_delete() -> dict:
    _civitai_delete_token()
    return {"ok": True, **_civitai_token_status()}


def api_civitai_token_test() -> dict:
    """Teste la connexion Civitai avec le token enregistré."""
    token = _civitai_get_token()
    if not token:
        return {"ok": False, "error": "Token Civitai absent. Enregistre-le d'abord."}
    try:
        data = _civitai_request("/models", {"limit": 1, "types": "LORA"})
        return {"ok": True, "message": "Civitai connection successful."}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}


# ---------- Hash SHA-256 du fichier (partiel pour les gros fichiers) ----------

def _read_safetensors_hash(path: str) -> tuple[str, str] | None:
    """Lit les métadonnées d'un fichier .safetensors et cherche un hash Civitai intégré.
    Le format safetensors commence par un entier 64-bit little-endian (taille du header JSON),
    suivi du JSON.
    Retourne (hash_value, hash_type) ou None si absent ou non fiable.
    Types reconnus : 'AutoV2' (CivitAI BlakeHash v2), 'SHA256' complet."""
    try:
        with open(path, "rb") as f:
            raw_size = f.read(8)
            if len(raw_size) < 8:
                return None
            import struct
            header_size = struct.unpack_from("<Q", raw_size)[0]
            if header_size > 100 * 1024 * 1024:  # sanity check
                return None
            header_bytes = f.read(header_size)
        metadata = json.loads(header_bytes.decode("utf-8", errors="replace"))
        # Les hashes sont dans "__metadata__" → "modelspec.hash_sha256" ou "sshs_model_hash"
        meta = metadata.get("__metadata__") or {}
        # Chercher dans l'ordre de préférence Civitai
        for key, htype in [
            ("modelspec.hash_sha256",  "SHA256"),
            ("sha256",                 "SHA256"),
            ("sshs_model_hash",        "AutoV2"),
            ("civitai_hash",           "AutoV2"),
        ]:
            val = (meta.get(key) or "").strip()
            if val and len(val) >= 32:
                log.info(f"[Civitai] Hash depuis metadata safetensors ({key}): {val[:12]}…")
                return (val.upper(), htype)
    except Exception as e:
        log.debug(f"[Civitai] Failed to read safetensors metadata: {e}")
    return None


def _sha256_full(path: str) -> str:
    """SHA-256 complet du fichier, par chunks de 8 Mo. Ne charge jamais le fichier entier.
    C'est le seul hash qu'on appelle 'SHA256' — le hash partiel précédent est supprimé."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8 * 1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        result = h.hexdigest().upper()
        log.info(f"[Civitai] Full SHA-256 computed: {result[:12]}…")
        return result
    except OSError as e:
        raise RuntimeError(f"Unable to read file for hash: {e}")


def _get_or_compute_hash(model_file_id: str, file_path: str, current_size: int,
                          current_mtime: float) -> tuple[str, str]:
    """Retourne (hash, hash_type) depuis le cache, ou le calcule.
    Stratégie :
      1. Cache DB valide (taille + mtime inchangés) → retour immédiat.
      2. Metadata safetensors intégrée → prioritaire et instantané.
      3. SHA-256 complet du fichier (peut être long pour les gros modèles).
    Le résultat est toujours mis en cache."""
    with db() as c:
        row = c.execute(
            "SELECT file_hash, hash_type, cached_size, cached_mtime "
            "FROM lora_civitai_metadata WHERE model_file_id=?",
            (model_file_id,)).fetchone()
    if (row and row["file_hash"]
            and row["cached_size"] == current_size
            and abs((row["cached_mtime"] or 0) - current_mtime) < 2):
        return (row["file_hash"], row["hash_type"] or "SHA256")

    # 1. Essayer les métadonnées internes du safetensors
    if file_path.lower().endswith(".safetensors"):
        result = _read_safetensors_hash(file_path)
        if result:
            file_hash, hash_type = result
            _save_hash_cache(model_file_id, file_hash, hash_type, current_size, current_mtime)
            return (file_hash, hash_type)

    # 2. SHA-256 complet
    log.info(f"[Civitai] Calcul SHA-256 complet : {os.path.basename(file_path)} "
             f"({current_size // 1024 // 1024} Mo) — peut prendre quelques secondes…")
    file_hash = _sha256_full(file_path)
    _save_hash_cache(model_file_id, file_hash, "SHA256", current_size, current_mtime)
    return (file_hash, "SHA256")


def _save_hash_cache(model_file_id: str, file_hash: str, hash_type: str,
                     size: int, mtime: float) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO lora_civitai_metadata(model_file_id, file_hash, hash_type, "
            "cached_size, cached_mtime) VALUES (?,?,?,?,?) "
            "ON CONFLICT(model_file_id) DO UPDATE SET "
            "file_hash=excluded.file_hash, hash_type=excluded.hash_type, "
            "cached_size=excluded.cached_size, cached_mtime=excluded.cached_mtime",
            (model_file_id, file_hash, hash_type, size, mtime),
        )


def _civitai_lookup_by_hash(file_hash: str) -> dict | None:
    """Interroge Civitai par hash. Retourne les données du modèle ou None si 404."""
    try:
        data = _civitai_request(f"/model-versions/by-hash/{file_hash}")
        return data
    except RuntimeError as e:
        msg = str(e)
        if "404" in msg or "not found" in msg.lower():
            return None
        raise


def _civitai_cache_preview_image(url: str, stem: str) -> tuple[str | None, str | None]:
    """Télécharge et met en cache localement une image Civitai.
    Retourne (fname, None) si succès, (None, error_msg) si échec.
    Vérifie les magic bytes, la taille max (20 Mo) et écrit sur disque de façon atomique."""
    if not url:
        return (None, "URL absente")

    # Déduire l'extension depuis l'URL (avant les paramètres query)
    url_path = url.split("?")[0].lower()
    ext = ".jpg"
    for candidate in (".webp", ".png", ".jpg", ".jpeg"):
        if url_path.endswith(candidate):
            ext = candidate
            break

    fname = f"civitai_{stem}{ext}"
    dest  = os.path.join(CIVITAI_CACHE_DIR, fname)

    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        log.info(f"[Civitai] Preview already cached: {fname}")
        return (fname, None)

    log.info(f"[Civitai] Downloading preview: {url[:80]}…")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AmiorAI/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except Exception as e:
        err = f"Network error: {e}"
        log.warning(f"[Civitai] {err}")
        return (None, err)

    if len(raw) > 20 * 1024 * 1024:
        err = f"Image trop volumineuse ({len(raw) // 1024} Ko > 20 Mo)"
        log.warning(f"[Civitai] {err}")
        return (None, err)

    # Vérifier magic bytes : PNG, JPEG, WebP, GIF
    MAGIC = {
        b'\x89PNG\r\n\x1a\n': ".png",
        b'\xff\xd8':          ".jpg",
        b'GIF':               ".gif",
    }
    detected_ext = None
    for magic, magic_ext in MAGIC.items():
        if raw[:len(magic)] == magic:
            detected_ext = magic_ext
            break
    if raw[8:12] == b'WEBP' or raw[:4] == b'RIFF':  # WebP
        detected_ext = ".webp"
    if detected_ext is None:
        err = f"Format image non reconnu (magic bytes: {raw[:4].hex()})"
        log.warning(f"[Civitai] {err}")
        return (None, err)

    # Corriger l'extension si nécessaire
    if detected_ext != ext:
        fname = f"civitai_{stem}{detected_ext}"
        dest  = os.path.join(CIVITAI_CACHE_DIR, fname)

    # Écriture atomique via fichier temporaire
    tmp = dest + ".tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, dest)
    except OSError as e:
        err = f"Write error: {e}"
        log.warning(f"[Civitai] {err}")
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return (None, err)

    # Vérifier que le fichier est bien là
    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
        err = "File was written but is missing or empty"
        log.warning(f"[Civitai] {err}")
        return (None, err)

    log.info(f"[Civitai] Preview downloaded: {fname} ({len(raw) // 1024} Ko)")
    return (fname, None)


def _civitai_enrich_one(model_file_row: dict) -> dict:
    """Identifie et enrichit une LoRA depuis Civitai.
    Retourne un dict diagnostics complet (jamais d'exception au niveau appelant).
    Champs retournés :
      model_file_id, status, hash_used, hash_origin, hash_type,
      civitai_model_id, civitai_model_name, civitai_version,
      preview_url, preview_path, preview_error,
      error (si échec global)
    """
    mfid   = model_file_row["id"]
    fpath  = model_file_row.get("path", "")
    fsize  = model_file_row.get("size", 0) or 0
    fmtime = model_file_row.get("mtime", 0) or 0
    fname  = model_file_row.get("name", mfid)

    base = {"model_file_id": mfid}

    if not fpath or not os.path.exists(fpath):
        log.warning(f"[Civitai] {fname} : file not found ({fpath})")
        return {**base, "status": "file_missing", "error": f"File not found: {fpath}"}

    # --- Hash ---
    try:
        file_hash, hash_type = _get_or_compute_hash(mfid, fpath, fsize, fmtime)
    except RuntimeError as e:
        log.warning(f"[Civitai] {fname} : hash computation error — {e}")
        return {**base, "status": "hash_error", "error": str(e)}

    # Déterminer l'origine du hash pour le debug
    hash_origin = "safetensors_metadata" if hash_type == "AutoV2" else \
                  ("safetensors_metadata" if (hash_type == "SHA256" and
                   fpath.lower().endswith(".safetensors") and
                   _read_safetensors_hash(fpath) is not None) else "computed_sha256")

    base.update({"hash_used": file_hash, "hash_type": hash_type, "hash_origin": hash_origin})
    log.info(f"[Civitai] {fname} : hash {hash_type} ({hash_origin}) = {file_hash[:12]}…")

    # --- Recherche Civitai ---
    try:
        civitai_data = _civitai_lookup_by_hash(file_hash)
    except RuntimeError as e:
        err = str(e)
        log.warning(f"[Civitai] {fname} : API error — {err}")
        if "401" in err:
            return {**base, "status": "token_error",   "error": err}
        if "429" in err:
            return {**base, "status": "rate_limit",    "error": err}
        return     {**base, "status": "network_error", "error": err}

    if civitai_data is None:
        log.info(f"[Civitai] {fname} : aucune correspondance pour le hash complet.")
        with db() as c:
            c.execute(
                "INSERT INTO lora_civitai_metadata(model_file_id, file_hash, hash_type, "
                "cached_size, cached_mtime, civitai_match_status, civitai_last_sync) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(model_file_id) DO UPDATE SET "
                "civitai_match_status=excluded.civitai_match_status, "
                "civitai_last_sync=excluded.civitai_last_sync, "
                "file_hash=excluded.file_hash, hash_type=excluded.hash_type, "
                "cached_size=excluded.cached_size, cached_mtime=excluded.cached_mtime",
                (mfid, file_hash, hash_type, fsize, fmtime, "no_match", time.time()),
            )
        return {**base, "status": "no_match"}

    # --- Correspondance trouvée ---
    model_info = civitai_data.get("model", {}) or {}
    model_name = model_info.get("name", "")
    version_name = civitai_data.get("name", "")
    log.info(f"[Civitai] {fname} : match found — model = {model_name!r}, "
             f"version = {version_name!r}")

    # Extraire la meilleure URL preview (chercher type=image, pas nsfw)
    preview_url = None
    for img in (civitai_data.get("images") or []):
        if img.get("url"):
            # préférer les images non-nsfw
            if not img.get("nsfw") or preview_url is None:
                preview_url = img["url"]
            if not img.get("nsfw"):
                break

    base.update({"preview_url": preview_url,
                 "civitai_model_id": civitai_data.get("modelId"),
                 "civitai_model_name": model_name,
                 "civitai_version": version_name})

    # --- Téléchargement preview ---
    civitai_preview_path = None
    preview_error = None
    if preview_url:
        stem = mfid[:20]
        civitai_preview_path, preview_error = _civitai_cache_preview_image(preview_url, stem)
        if preview_error:
            log.warning(f"[Civitai] {fname} : preview not downloaded — {preview_error}")
        else:
            log.info(f"[Civitai] {fname} : preview downloaded — {civitai_preview_path}")
    else:
        log.info(f"[Civitai] {fname} : match found but no preview URL.")

    tags     = model_info.get("tags") or []
    triggers = civitai_data.get("trainedWords") or []
    now      = time.time()

    # Statut granulaire
    if civitai_preview_path:
        match_status = "found_with_preview"
    elif preview_url and preview_error:
        match_status = "found_preview_error"
    elif not preview_url:
        match_status = "found_no_preview_url"
    else:
        match_status = "found"

    with db() as c:
        c.execute(
            "INSERT INTO lora_civitai_metadata("
            "model_file_id, file_hash, hash_type, cached_size, cached_mtime, "
            "civitai_model_id, civitai_model_version_id, civitai_model_name, "
            "civitai_version_name, civitai_creator, civitai_base_model, civitai_url, "
            "civitai_tags_json, civitai_trigger_words_json, "
            "civitai_preview_url, civitai_preview_path, "
            "civitai_match_status, civitai_last_sync, civitai_last_error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(model_file_id) DO UPDATE SET "
            "file_hash=excluded.file_hash, hash_type=excluded.hash_type, "
            "cached_size=excluded.cached_size, cached_mtime=excluded.cached_mtime, "
            "civitai_model_id=excluded.civitai_model_id, "
            "civitai_model_version_id=excluded.civitai_model_version_id, "
            "civitai_model_name=excluded.civitai_model_name, "
            "civitai_version_name=excluded.civitai_version_name, "
            "civitai_creator=excluded.civitai_creator, "
            "civitai_base_model=excluded.civitai_base_model, "
            "civitai_url=excluded.civitai_url, "
            "civitai_tags_json=excluded.civitai_tags_json, "
            "civitai_trigger_words_json=excluded.civitai_trigger_words_json, "
            "civitai_preview_url=excluded.civitai_preview_url, "
            "civitai_preview_path=excluded.civitai_preview_path, "
            "civitai_match_status=excluded.civitai_match_status, "
            "civitai_last_sync=excluded.civitai_last_sync, "
            "civitai_last_error=excluded.civitai_last_error",
            (mfid, file_hash, hash_type, fsize, fmtime,
             civitai_data.get("modelId"), civitai_data.get("id"),
             model_name, version_name,
             (model_info.get("creator") or {}).get("username"),
             civitai_data.get("baseModel"),
             f"https://civitai.com/models/{civitai_data.get('modelId')}",
             json.dumps(tags, ensure_ascii=False),
             json.dumps(triggers, ensure_ascii=False),
             preview_url, civitai_preview_path,
             match_status, now, preview_error),
        )

    return {
        **base,
        "status":            match_status,
        "preview_path":      civitai_preview_path,
        "preview_error":     preview_error,
        "preview_cached":    bool(civitai_preview_path),
        "civitai_version_id": civitai_data.get("id"),
    }


def api_civitai_enrich_one(model_file_id: str) -> dict:
    """Enrichit une seule LoRA depuis Civitai (action manuelle par carte)."""
    token = _civitai_get_token()
    if not token:
        raise RuntimeError("Token Civitai absent. Configure-le dans la page LoRA.")
    with db() as c:
        row = c.execute("SELECT * FROM model_files WHERE id=?", (model_file_id,)).fetchone()
    if not row:
        raise RuntimeError(f"Model file not found: {model_file_id}")
    return _civitai_enrich_one(dict(row))


# Annulation de synchronisation globale
_civitai_sync_cancel = threading.Event()
_civitai_sync_lock   = threading.Lock()
_civitai_sync_state: dict = {}


def api_civitai_sync(mode: str = "missing") -> dict:
    """Lance la synchronisation globale en arrière-plan.
    mode : 'missing' | 'no_preview' | 'stale' (30j) | 'all'
    Retourne immédiatement {job_id}."""
    token = _civitai_get_token()
    if not token:
        raise RuntimeError("Token Civitai absent. Configure-le dans la page LoRA.")
    if not _civitai_sync_lock.acquire(blocking=False):
        raise RuntimeError("A synchronization is already running.")

    job_id = new_id()
    _civitai_sync_cancel.clear()
    _civitai_sync_state.clear()
    _civitai_sync_state.update({"job_id": job_id, "running": True, "done": 0, "total": 0,
                                 "found": 0, "no_match": 0, "errors": 0, "preview_cached": 0,
                                 "cancelled": False, "message": "Recherche des LoRA…"})

    def _run():
        try:
            # Requête des LoRA éligibles selon le mode
            with db() as c:
                base_q = ("SELECT mf.* FROM model_files mf "
                          "LEFT JOIN lora_civitai_metadata cm ON cm.model_file_id = mf.id "
                          "WHERE mf.kind='lora' AND mf.missing=0")
                now30 = time.time() - 30 * 86400
                if mode == "missing":
                    rows = c.execute(base_q + " AND (cm.model_file_id IS NULL OR cm.civitai_match_status IS NULL)").fetchall()
                elif mode == "no_preview":
                    rows = c.execute(base_q + " AND (cm.civitai_preview_path IS NULL)").fetchall()
                elif mode == "stale":
                    rows = c.execute(base_q + " AND (cm.civitai_last_sync IS NULL OR cm.civitai_last_sync < ?)",
                                     (now30,)).fetchall()
                else:  # 'all'
                    rows = c.execute("SELECT * FROM model_files WHERE kind='lora' AND missing=0").fetchall()

            total = len(rows)
            _civitai_sync_state["total"]   = total
            _civitai_sync_state["message"] = f"{total} LoRA to synchronize…"

            for i, row in enumerate(rows):
                if _civitai_sync_cancel.is_set():
                    _civitai_sync_state["cancelled"] = True
                    _civitai_sync_state["message"]   = "Synchronization canceled."
                    break
                _civitai_sync_state["message"] = f"[{i+1}/{total}] {row['name']}…"
                res = _civitai_enrich_one(dict(row))
                _civitai_sync_state["done"] += 1
                st = res.get("status", "")
                if st == "found":
                    _civitai_sync_state["found"] += 1
                    if res.get("preview_cached"):
                        _civitai_sync_state["preview_cached"] += 1
                elif st == "no_match":
                    _civitai_sync_state["no_match"] += 1
                elif st in ("rate_limit", "token_error"):
                    _civitai_sync_state["errors"] += 1
                    _civitai_sync_state["message"] = f"Stopped:{res.get('error')}"
                    break
                else:
                    _civitai_sync_state["errors"] += 1
                # Pause polic rate-limit : 0.3 s entre requêtes
                time.sleep(0.3)

            if not _civitai_sync_state.get("cancelled"):
                d = _civitai_sync_state
                _civitai_sync_state["message"] = (
                    f"Finished — {d['found']} found · {d['no_match']} sans fiche · "
                    f"{d['errors']} erreurs · {d['preview_cached']} previews mises en cache"
                )
        finally:
            _civitai_sync_state["running"] = False
            _civitai_sync_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


def api_civitai_sync_status() -> dict:
    return dict(_civitai_sync_state)


def api_civitai_sync_cancel() -> dict:
    _civitai_sync_cancel.set()
    return {"ok": True}


def api_civitai_metadata_get(model_file_id: str) -> dict:
    """Retourne les métadonnées Civitai pour un model_file_id, avec champs effectifs."""
    with db() as c:
        row = c.execute(
            "SELECT * FROM lora_civitai_metadata WHERE model_file_id=?",
            (model_file_id,)).fetchone()
    if not row:
        return {"model_file_id": model_file_id, "civitai_match_status": None}
    d = dict(row)
    for field in ("civitai_tags_json", "civitai_trigger_words_json"):
        try:
            d[field.replace("_json", "")] = json.loads(d.get(field) or "[]")
        except Exception:
            d[field.replace("_json", "")] = []
    _civitai_add_effective_fields(d)
    return d


def api_civitai_metadata_list() -> dict:
    """Retourne toutes les métadonnées Civitai indexées par model_file_id."""
    with db() as c:
        rows = c.execute("SELECT * FROM lora_civitai_metadata").fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        for field in ("civitai_tags_json", "civitai_trigger_words_json"):
            try:
                d[field.replace("_json", "")] = json.loads(d.get(field) or "[]")
            except Exception:
                d[field.replace("_json", "")] = []
        _civitai_add_effective_fields(d)
        out[d["model_file_id"]] = d
    return out


def _civitai_add_effective_fields(d: dict) -> None:
    """Injecte in-place les champs 'effective_type' et 'effective_family' selon la priorité :
    1. Override manuel  2. Données Civitai (si confirmées)  3. Automatic detection  4. unknown"""
    manual_type   = (d.get("manual_file_type") or "").strip()
    manual_family = (d.get("manual_family")    or "").strip()
    auto_type     = (d.get("detected_file_type") or "").strip()
    auto_family   = (d.get("detected_family")    or "").strip()
    civ_family    = (d.get("civitai_base_model") or "").strip()
    confirmed     = bool(d.get("civitai_association_confirmed"))
    src           = d.get("identification_source") or "auto"

    d["effective_type"]   = manual_type   or auto_type   or "lora"
    d["effective_family"] = manual_family or (civ_family if confirmed else "") or auto_family or ""
    d["identification_source_label"] = (
        "Override manuel" if (manual_type or manual_family) else
        "Civitai (confirmed)" if (confirmed and civ_family) else
        "Automatic detection"
    )


# --------------------------------------------------------------------------- #
#  Association manuelle via URL Civitai
# --------------------------------------------------------------------------- #

_CIVITAI_ALLOWED_DOMAINS = frozenset({
    "civitai.com", "www.civitai.com",
    "civitai.red", "www.civitai.red",
})

# Paramètres à ne jamais logger ni sauvegarder (peuvent contenir un token)
_CIVITAI_SENSITIVE_PARAMS = frozenset({"token", "key", "apiKey", "Authorization"})


def _sanitize_civitai_url(url: str) -> str:
    """Retourne l'URL nettoyée des paramètres sensibles, pour log et DB."""
    try:
        p = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        safe_qs = {k: v for k, v in qs.items() if k not in _CIVITAI_SENSITIVE_PARAMS}
        clean = p._replace(query=urllib.parse.urlencode(safe_qs, doseq=True))
        return urllib.parse.urlunparse(clean)
    except Exception:
        return "[URL non affichable]"


def _parse_civitai_url(url: str) -> dict:
    """Parse une URL Civitai et retourne un dict avec model_id, version_id, type.

    Formats acceptés (civitai.com et civitai.red) :
      /models/<model_id>
      /models/<model_id>/<slug>
      /models/<model_id>?modelVersionId=<version_id>
      /models/<model_id>/<slug>?modelVersionId=<version_id>
      /models/<model_id>/reviews?modelVersionId=<version_id>
      /model-versions/<version_id>
      /api/download/models/<version_id>       ← lien de téléchargement

    Retourne : {"model_id": int|None, "version_id": int|None, "url_type": str}
    Lève RuntimeError si le domaine n'est pas autorisé ou si rien n'est extrait.
    Ne logue jamais l'URL brute si elle contient des paramètres sensibles.
    """
    url = (url or "").strip()
    if not url:
        raise RuntimeError("URL vide.")

    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower().lstrip("www.")
    # Normaliser avec www. pour la comparaison
    domain_check = parsed.netloc.lower()
    if domain_check not in _CIVITAI_ALLOWED_DOMAINS:
        # Essai sans www.
        bare = domain_check.removeprefix("www.")
        if bare not in {d.removeprefix("www.") for d in _CIVITAI_ALLOWED_DOMAINS}:
            raise RuntimeError(
                f"Unauthorized domain: '{parsed.netloc}'. "
                f"Accepted domains: civitai.com, civitai.red."
            )

    parts  = [p for p in parsed.path.split("/") if p]
    qs     = urllib.parse.parse_qs(parsed.query)
    result = {"model_id": None, "version_id": None, "url_type": "unknown"}

    def _int(s):
        try:
            return int(s)
        except (ValueError, TypeError):
            return None

    # --- /model-versions/<version_id> ---
    if len(parts) >= 2 and parts[0] == "model-versions":
        result["version_id"] = _int(parts[1])
        result["url_type"]   = "version_direct"
        if result["version_id"]:
            return result

    # --- /api/download/models/<version_id> ---
    if "download" in parts and "models" in parts:
        dl_idx = parts.index("models")
        if dl_idx + 1 < len(parts):
            result["version_id"] = _int(parts[dl_idx + 1])
            result["url_type"]   = "download_link"
            # Ne pas sauvegarder les params (peuvent contenir un token) — on ne garde que l'ID
            if result["version_id"]:
                return result

    # --- /models/<model_id>[/<slug>][?modelVersionId=...] ---
    for i, part in enumerate(parts):
        if part == "models" and i + 1 < len(parts):
            result["model_id"] = _int(parts[i + 1])
            result["url_type"] = "model"
            break

    vid = qs.get("modelVersionId", [None])[0]
    if vid:
        result["version_id"] = _int(vid)
        result["url_type"]   = "model_with_version"

    if not result["model_id"] and not result["version_id"]:
        raise RuntimeError(
            "Unable to extract a Civitai identifier from this link. "
            "Accepted forms: /models/<id>, /model-versions/<id>, /api/download/models/<id>."
        )
    return result


def _civitai_extract_preview(version_data: dict) -> str | None:
    """Extrait la meilleure URL de preview depuis les données d'une version Civitai."""
    for img in (version_data.get("images") or []):
        if img.get("url") and not img.get("nsfw"):
            return img["url"]
    for img in (version_data.get("images") or []):
        if img.get("url"):
            return img["url"]
    return None


def _civitai_format_version(v: dict, model_name: str) -> dict:
    """Formate les données d'une version Civitai pour affichage de sélection."""
    return {
        "version_id":       v.get("id"),
        "version_name":     v.get("name", ""),
        "base_model":       v.get("baseModel", ""),
        "published_at":     (v.get("publishedAt") or "")[:10],
        "trigger_words":    v.get("trainedWords") or [],
        "preview_url":      _civitai_extract_preview(v),
        "civitai_model_name": model_name,
    }


def api_civitai_fetch_by_url(url: str) -> dict:
    """Récupère les métadonnées Civitai depuis une URL sans les enregistrer.
    Si le lien cible un modèle sans version précise et qu'il y a plusieurs versions,
    retourne needs_version_selection=True avec la liste des versions.
    Retourne les données formatées pour affichage de confirmation."""
    parsed_url = _parse_civitai_url(url)
    safe_url   = _sanitize_civitai_url(url)   # version sans paramètres sensibles
    log.info(f"[Civitai] Fetch par URL : {safe_url} → {parsed_url}")

    model_id   = parsed_url.get("model_id")
    version_id = parsed_url.get("version_id")

    if version_id:
        # Version connue directement
        data       = _civitai_request(f"/model-versions/{version_id}")
        model_info = data.get("model", {}) or {}
        creator    = (model_info.get("creator") or {})
        return {
            "needs_version_selection": False,
            "civitai_model_id":         data.get("modelId"),
            "civitai_model_version_id": data.get("id"),
            "civitai_model_name":       model_info.get("name", ""),
            "civitai_version_name":     data.get("name", ""),
            "civitai_creator":          creator.get("username", "") if isinstance(creator, dict) else str(creator or ""),
            "civitai_base_model":       data.get("baseModel", ""),
            "civitai_url":              f"https://civitai.com/models/{data.get('modelId')}",
            "civitai_tags":             (model_info.get("tags") or []),
            "civitai_trigger_words":    data.get("trainedWords") or [],
            "civitai_preview_url":      _civitai_extract_preview(data),
            "source_url":               safe_url,
        }

    # model_id connu, pas de version précisée
    model_data = _civitai_request(f"/models/{model_id}")
    versions   = model_data.get("modelVersions") or []
    model_name = model_data.get("name", "")
    creator    = (model_data.get("creator") or {})

    if not versions:
        raise RuntimeError("This model has no available version on Civitai.")

    if len(versions) == 1:
        # Une seule version : pas de sélection nécessaire
        v = versions[0]
        return {
            "needs_version_selection": False,
            "civitai_model_id":         model_data.get("id"),
            "civitai_model_version_id": v.get("id"),
            "civitai_model_name":       model_name,
            "civitai_version_name":     v.get("name", ""),
            "civitai_creator":          creator.get("username", "") if isinstance(creator, dict) else str(creator or ""),
            "civitai_base_model":       v.get("baseModel", ""),
            "civitai_url":              f"https://civitai.com/models/{model_data.get('id')}",
            "civitai_tags":             model_data.get("tags") or [],
            "civitai_trigger_words":    v.get("trainedWords") or [],
            "civitai_preview_url":      _civitai_extract_preview(v),
            "source_url":               safe_url,
        }

    # Plusieurs versions : demander sélection à l'utilisateur
    return {
        "needs_version_selection": True,
        "civitai_model_id":   model_data.get("id"),
        "civitai_model_name": model_name,
        "civitai_creator":    creator.get("username", "") if isinstance(creator, dict) else str(creator or ""),
        "civitai_url":        f"https://civitai.com/models/{model_data.get('id')}",
        "source_url":         safe_url,
        "versions":           [_civitai_format_version(v, model_name) for v in versions],
    }


def api_civitai_fetch_version(version_id: int) -> dict:
    """Récupère une version précise de Civitai (appelée après sélection de version)."""
    data       = _civitai_request(f"/model-versions/{version_id}")
    model_info = data.get("model", {}) or {}
    creator    = (model_info.get("creator") or {})
    return {
        "needs_version_selection": False,
        "civitai_model_id":         data.get("modelId"),
        "civitai_model_version_id": data.get("id"),
        "civitai_model_name":       model_info.get("name", ""),
        "civitai_version_name":     data.get("name", ""),
        "civitai_creator":          creator.get("username", "") if isinstance(creator, dict) else str(creator or ""),
        "civitai_base_model":       data.get("baseModel", ""),
        "civitai_url":              f"https://civitai.com/models/{data.get('modelId')}",
        "civitai_tags":             (model_info.get("tags") or []),
        "civitai_trigger_words":    data.get("trainedWords") or [],
        "civitai_preview_url":      _civitai_extract_preview(data),
    }


def api_civitai_associate(model_file_id: str, civitai_data: dict) -> dict:
    """Confirme et enregistre une association manuelle Civitai pour une LoRA locale.
    civitai_data doit contenir les champs retournés par api_civitai_fetch_by_url.
    Ne remplace pas une preview locale existante."""
    if not model_file_id:
        raise RuntimeError("model_Missing file_id.")

    with db() as c:
        row = c.execute("SELECT * FROM model_files WHERE id=?", (model_file_id,)).fetchone()
    if not row:
        raise RuntimeError(f"Model file not found: {model_file_id}")

    # Télécharger la preview si disponible (sans écraser une preview locale)
    preview_url = civitai_data.get("civitai_preview_url")
    civitai_preview_path = None
    preview_error = None
    if preview_url:
        stem = model_file_id[:20] + "_manual"
        # Vérifier si une preview Civitai existe déjà
        with db() as c:
            existing = c.execute(
                "SELECT civitai_preview_path FROM lora_civitai_metadata WHERE model_file_id=?",
                (model_file_id,)).fetchone()
        if existing and existing["civitai_preview_path"]:
            civitai_preview_path = existing["civitai_preview_path"]
            log.info(f"[Civitai] Existing Civitai preview reused: {civitai_preview_path}")
        else:
            civitai_preview_path, preview_error = _civitai_cache_preview_image(preview_url, stem)

    tags_json     = json.dumps(civitai_data.get("civitai_tags", []),          ensure_ascii=False)
    triggers_json = json.dumps(civitai_data.get("civitai_trigger_words", []), ensure_ascii=False)
    now = time.time()

    with db() as c:
        c.execute(
            "INSERT INTO lora_civitai_metadata("
            "model_file_id, civitai_model_id, civitai_model_version_id, civitai_model_name, "
            "civitai_version_name, civitai_creator, civitai_base_model, civitai_url, "
            "civitai_tags_json, civitai_trigger_words_json, "
            "civitai_preview_url, civitai_preview_path, "
            "civitai_match_status, civitai_manual_url, civitai_association_confirmed, "
            "identification_source, civitai_last_sync, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(model_file_id) DO UPDATE SET "
            "civitai_model_id=excluded.civitai_model_id, "
            "civitai_model_version_id=excluded.civitai_model_version_id, "
            "civitai_model_name=excluded.civitai_model_name, "
            "civitai_version_name=excluded.civitai_version_name, "
            "civitai_creator=excluded.civitai_creator, "
            "civitai_base_model=excluded.civitai_base_model, "
            "civitai_url=excluded.civitai_url, "
            "civitai_tags_json=excluded.civitai_tags_json, "
            "civitai_trigger_words_json=excluded.civitai_trigger_words_json, "
            "civitai_preview_url=excluded.civitai_preview_url, "
            "civitai_preview_path=excluded.civitai_preview_path, "
            "civitai_match_status=excluded.civitai_match_status, "
            "civitai_manual_url=excluded.civitai_manual_url, "
            "civitai_association_confirmed=excluded.civitai_association_confirmed, "
            "identification_source=excluded.identification_source, "
            "civitai_last_sync=excluded.civitai_last_sync, "
            "updated_at=excluded.updated_at",
            (model_file_id,
             civitai_data.get("civitai_model_id"),
             civitai_data.get("civitai_model_version_id"),
             civitai_data.get("civitai_model_name"),
             civitai_data.get("civitai_version_name"),
             civitai_data.get("civitai_creator"),
             civitai_data.get("civitai_base_model"),
             civitai_data.get("civitai_url"),
             tags_json, triggers_json,
             preview_url, civitai_preview_path,
             "found_with_preview" if civitai_preview_path else "found_no_preview_url",
             civitai_data.get("source_url"),
             1,  # confirmed
             "civitai",
             now, now),
        )
    log.info(f"[Civitai] Manual association confirmed for {model_file_id} "
             f"→ {civitai_data.get('civitai_model_name')!r}")
    return {"ok": True, "preview_cached": bool(civitai_preview_path), "preview_error": preview_error}


def api_lora_set_identification(model_file_id: str, manual_file_type: str | None,
                                 manual_family: str | None, reset: bool = False) -> dict:
    """Enregistre ou réinitialise l'identification manuelle (type + famille) d'une LoRA.
    reset=True : efface uniquement les overrides manuels, laisse l'auto intact."""
    if not model_file_id:
        raise RuntimeError("model_Missing file_id.")

    if reset:
        with db() as c:
            c.execute(
                "INSERT INTO lora_civitai_metadata(model_file_id, manual_file_type, manual_family, "
                "identification_source, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(model_file_id) DO UPDATE SET "
                "manual_file_type=NULL, manual_family=NULL, "
                "identification_source='auto', updated_at=excluded.updated_at",
                (model_file_id, None, None, "auto", time.time()),
            )
        log.info(f"[LoRA] Identification reset (auto) for {model_file_id}")
        return {"ok": True, "reset": True}

    with db() as c:
        c.execute(
            "INSERT INTO lora_civitai_metadata(model_file_id, manual_file_type, manual_family, "
            "identification_source, updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(model_file_id) DO UPDATE SET "
            "manual_file_type=excluded.manual_file_type, "
            "manual_family=excluded.manual_family, "
            "identification_source='manual', "
            "updated_at=excluded.updated_at",
            (model_file_id,
             (manual_file_type or "").strip() or None,
             (manual_family or "").strip() or None,
             "manual",
             time.time()),
        )
    log.info(f"[LoRA] Identification manuelle pour {model_file_id}: "
             f"type={manual_file_type!r} famille={manual_family!r}")
    return {"ok": True, "manual_file_type": manual_file_type, "manual_family": manual_family}


def _civitai_preview_url_for_card(civitai_meta: dict | None) -> str | None:
    """Retourne l'URL locale de la preview Civitai si disponible."""
    if not civitai_meta:
        return None
    fp = civitai_meta.get("civitai_preview_path")
    if fp:
        return f"/lora_preview/civitai/{fp}"
    return None



# --------------------------------------------------------------------------- #
#  Fonctions helpers i18n (routes /api/i18n/*)
#  generate_locales importé directement — pas de subprocess, compatible .exe
# --------------------------------------------------------------------------- #

def _get_i18n_paths():
    """Retourne (master_path, locales_dir, backup_dir)."""
    i18n_root  = os.path.join(CODE_ROOT, "resources", "i18n")
    master     = os.path.join(i18n_root, "translations_master.xlsx")
    locales    = os.path.join(i18n_root, "locales")
    backup     = os.path.join(i18n_root, "locales_backup")
    return master, locales, backup


def _i18n_stats() -> dict:
    """Retourne des stats sur les locales JSON."""
    _, locales_dir, _ = _get_i18n_paths()
    langs = ["fr", "en", "es", "de"]
    stats = {"langs": {}, "total_keys_en": 0}

    def _count(obj, prefix=""):
        keys = []
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            full = (prefix + "." + k) if prefix else k
            if isinstance(v, dict):
                keys.extend(_count(v, full))
            else:
                keys.append(full)
        return keys

    en_path = os.path.join(locales_dir, "en.json")
    en_keys = []
    if os.path.isfile(en_path):
        with open(en_path, "r", encoding="utf-8") as f:
            en_data = json.load(f)
        en_keys = _count(en_data)
        stats["total_keys_en"] = len(en_keys)

    for lang in langs:
        p = os.path.join(locales_dir, lang + ".json")
        if not os.path.isfile(p):
            stats["langs"][lang] = {"exists": False, "keys": 0, "missing": len(en_keys)}
            continue
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        keys = _count(data)
        missing = [k for k in en_keys if k not in keys]
        stats["langs"][lang] = {
            "exists": True,
            "keys": len(keys),
            "missing": len(missing),
            "missing_keys": missing[:20],
        }
    return stats


def _i18n_call_generate(master_path=None, dry_run=False) -> dict:
    """Appelle generate_locales() directement (pas de subprocess)."""
    try:
        # Translation generator is stored beside the i18n resources used at runtime.
        i18n_tools_dir = os.path.join(CODE_ROOT, "resources", "i18n")
        if i18n_tools_dir not in sys.path:
            sys.path.insert(0, i18n_tools_dir)
        from generate_locales import generate_locales as _gen
    except ImportError as e:
        return {
            "ok": False,
            "error_code": "IMPORT_FAILED",
            "message": f"Impossible d'importer generate_locales : {e}",
            "details": f"generate_locales.py expected in: {i18n_tools_dir}",
        }
    mp, locales_dir, _ = _get_i18n_paths()
    return _gen(master_path or mp, locales_dir, dry_run=dry_run)


def _i18n_restore_backup() -> dict:
    """Restaure la dernière sauvegarde des locales JSON."""
    import shutil
    _, locales_dir, backup_dir = _get_i18n_paths()
    if not os.path.isdir(backup_dir):
        return {
            "ok": False,
            "error_code": "NO_BACKUP",
            "message": "No backup found.",
            "details": f"Searched folder: {backup_dir}",
        }
    restored = []
    errors = []
    for fname in os.listdir(backup_dir):
        if fname.endswith(".json"):
            src = os.path.join(backup_dir, fname)
            dst = os.path.join(locales_dir, fname)
            try:
                shutil.copy2(src, dst)
                restored.append(fname)
            except OSError as e:
                errors.append(f"{fname} : {e}")
    if errors:
        return {
            "ok": False,
            "error_code": "RESTORE_PARTIAL",
            "message": f"Restauration partielle ({len(restored)} fichiers).",
            "details": "\n".join(errors),
        }
    return {"ok": bool(restored), "restored": restored, "message": f"{len(restored)} file(s) restored."}


# --------------------------------------------------------------------------- #
#  Prompts avancés — overrides utilisateur
#
#  Logique de priorité (même pour CHARGEN_SYSTEM et SCENE_PLANNER) :
#    1. Override utilisateur sauvegardé dans settings (non vide)
#    2. Prompt officiel intégré dans le code (DEFAULT)
#
#  Les prompts officiels ne sont jamais modifiés dans les fichiers source.
#  L'override est stocké dans settings.json et effacé sur reset.
# --------------------------------------------------------------------------- #

# Clés JSON dans les 7 champs attendus par le Scene Planner
_SCENE_PLANNER_REQUIRED_KEYS = ("pose_action", "framing", "expression", "outfit",
                                 "environment", "lighting", "mood")


def get_effective_chargen_system() -> str:
    """Retourne le system prompt CHARGEN effectif (override ou prompt officiel localisé).
    Utilisé uniquement pour l'affichage dans les Prompts avancés — la génération réelle
    passe par build_chargen_messages() dans generate_character()."""
    settings = get_settings()
    override = (settings.get("override_chargen_system") or "").strip()
    if override:
        return override
    lang = settings.get("ui_language", "en").strip().lower()
    from i18n_backend import _CHARGEN_SYSTEM, SUPPORTED as _SUPP
    return _CHARGEN_SYSTEM.get(lang if lang in _SUPP else "en", _CHARGEN_SYSTEM["en"])


def get_effective_scene_planner_prompt() -> str:
    """Retourne SCENE_PLANNER_SYSTEM_PROMPT Flux effectif (override ou officiel)."""
    import image_prompt_builder as _ipb
    override = (get_settings().get("override_scene_planner_prompt") or "").strip()
    return override if override else _ipb.SCENE_PLANNER_SYSTEM_PROMPT


def get_effective_krea_scene_planner_prompt() -> str:
    """Retourne le prompt scene planner Krea 2 effectif (override ou officiel)."""
    override = (get_settings().get("override_krea_scene_planner_prompt") or "").strip()
    return override if override else krea_prompt_builder.KREA_SCENE_PLANNER_SYSTEM_PROMPT


def api_advanced_prompts_get() -> dict:
    """Retourne les prompts avancés officiels/overrides/statuts."""
    import image_prompt_builder as _ipb
    settings = get_settings()
    chargen_override = (settings.get("override_chargen_system") or "").strip()
    scene_override   = (settings.get("override_scene_planner_prompt") or "").strip()
    krea_override    = (settings.get("override_krea_scene_planner_prompt") or "").strip()
    conv_override    = (settings.get("override_conversation_style_prompt") or "").strip()
    official_chargen = get_effective_chargen_system()
    return {
        "chargen": {
            "key":            "override_chargen_system",
            "title":          "Character creation prompt",
            "description":    "System prompt used when generating or enriching a character by AI. Note: without override, the prompt changes according to the active language.",
            "official":       official_chargen,
            "override":       chargen_override,
            "has_override":   bool(chargen_override),
            "effective":      chargen_override if chargen_override else official_chargen,
        },
        "conversation_style": {
            "key":            "override_conversation_style_prompt",
            "title":          "Conversation roleplay style",
            "description":    "Global style instruction appended to each character conversation prompt. Controls narration precision, action detail and roleplay tone.",
            "official":       CONVERSATION_STYLE_PROMPT,
            "override":       conv_override,
            "has_override":   bool(conv_override),
            "effective":      conv_override if conv_override else CONVERSATION_STYLE_PROMPT,
        },
        "scene_planner": {
            "key":            "override_scene_planner_prompt",
            "title":          "Flux Scene Planner",
            "description":    "System prompt used to analyze context and produce the 7 visual JSON fields for Flux image prompts.",
            "official":       _ipb.SCENE_PLANNER_SYSTEM_PROMPT,
            "override":       scene_override,
            "has_override":   bool(scene_override),
            "effective":      scene_override if scene_override else _ipb.SCENE_PLANNER_SYSTEM_PROMPT,
            "required_keys":  list(_SCENE_PLANNER_REQUIRED_KEYS),
        },
        "krea_scene_planner": {
            "key":            "override_krea_scene_planner_prompt",
            "title":          "Krea 2 Scene Planner",
            "description":    "System prompt used by the utility model to convert chat moments into explicit Krea 2 JSON scene fields, including user/character interactions.",
            "official":       krea_prompt_builder.KREA_SCENE_PLANNER_SYSTEM_PROMPT,
            "override":       krea_override,
            "has_override":   bool(krea_override),
            "effective":      krea_override if krea_override else krea_prompt_builder.KREA_SCENE_PLANNER_SYSTEM_PROMPT,
            "required_keys":  list(krea_prompt_builder.KREA_REQUIRED_FIELDS),
        },
    }


def api_advanced_prompts_save(key: str, value: str) -> dict:
    """Sauvegarde un override de prompt. Valide les clés JSON pour le Scene Planner."""
    allowed_prompt_keys = (
        "override_chargen_system",
        "override_scene_planner_prompt",
        "override_krea_scene_planner_prompt",
        "override_conversation_style_prompt",
    )
    if key not in allowed_prompt_keys:
        raise RuntimeError(f"Unknown prompt key: {key!r}")
    value = (value or "").strip()
    if not value:
        raise RuntimeError("The prompt cannot be empty. Use Reset to restore the official prompt.")

    # Validation spécifique Scene Planner
    warnings_out = []
    if key == "override_scene_planner_prompt":
        missing = [k for k in _SCENE_PLANNER_REQUIRED_KEYS if f'"{k}"' not in value]
        if missing:
            warnings_out.append(
                f"Missing JSON keys in Flux Scene Planner prompt: {', '.join(missing)}. "
                f"Image generations may fall back or fail."
            )
    elif key == "override_krea_scene_planner_prompt":
        missing = [k for k in krea_prompt_builder.KREA_REQUIRED_FIELDS if f'"{k}"' not in value]
        if missing:
            warnings_out.append(
                f"Missing JSON keys in Krea 2 Scene Planner prompt: {', '.join(missing)}. "
                f"Krea image generations may fall back or fail."
            )

    # Sauvegarder l'override précédent avant écrasement (pour Restaurer)
    current = (get_settings().get(key) or "").strip()
    backup_key = key + "_backup"
    if current:
        save_settings({backup_key: current})

    save_settings({key: value})
    log.info(f"[Prompts] Override saved for {key} ({len(value)} chars)")
    return {"ok": True, "key": key, "warnings": warnings_out}


def api_advanced_prompts_reset(key: str | None = None) -> dict:
    """Réinitialise un ou tous les overrides de prompts.
    key=None → reset global (les deux prompts)."""
    keys = [
        "override_chargen_system",
        "override_scene_planner_prompt",
        "override_krea_scene_planner_prompt",
        "override_conversation_style_prompt",
    ]
    if key is not None:
        if key not in keys:
            raise RuntimeError(f"Unknown key: {key!r}")
        keys = [key]
    reset_data = {k: "" for k in keys}
    save_settings(reset_data)
    log.info(f"[Prompts] Reset override(s) : {keys}")
    return {"ok": True, "reset_keys": keys}


def api_advanced_prompts_restore(key: str) -> dict:
    """Restaure l'override précédent (avant la dernière sauvegarde)."""
    backup_key = key + "_backup"
    backup = (get_settings().get(backup_key) or "").strip()
    if not backup:
        raise RuntimeError("No previous version to restore.")
    save_settings({key: backup, backup_key: ""})
    return {"ok": True, "restored": backup}


def api_model_folders_list():
    """Retourne la liste des dossiers surveillés."""
    with db() as c:
        rows = c.execute(
            "SELECT * FROM model_folders ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def api_model_folder_add(path, kind_hint=None):
    # Normaliser le chemin (supprimer les slashes finaux, résoudre les doubles séparateurs)
    path = os.path.normpath((path or "").strip())
    if not path or path == ".":
        raise RuntimeError("Missing folder path.")
    if not os.path.isdir(path):
        raise RuntimeError(f"This folder does not exist or is not accessible: {path}")
    with db() as c:
        # Vérifier doublons en normalisant aussi les chemins existants
        existing = c.execute("SELECT id, path FROM model_folders").fetchall()
        for row in existing:
            if os.path.normpath(row["path"]) == path:
                raise RuntimeError("This folder, or a normalized equivalent, is already in the list.")
        fid = new_id()
        c.execute("INSERT INTO model_folders(id, path, kind_hint, enabled, created_at, last_count) "
                  "VALUES (?,?,?,1,?,0)", (fid, path, kind_hint or None, time.time()))
        folder_row = c.execute("SELECT * FROM model_folders WHERE id=?", (fid,)).fetchone()
    # Scan immédiat du dossier après ajout
    scan_result = None
    try:
        with db() as c:
            scan_result = model_catalog.rescan_folder(c, new_id, folder_row)
        log.info(f"[Library] Folder added and scanned: {path} → {scan_result['count']} file(s)")
    except Exception as e:
        log.warning(f"[Library] Post-add scan failed: {e}")
    # Pour kind_hint=lora : forcer kind=lora sur tous les .safetensors et .pt non classifiés
    if kind_hint == "lora":
        try:
            with db() as c:
                c.execute(
                    "UPDATE model_files SET kind='lora', detected_kind='lora', "
                    "identification_source=CASE WHEN identification_source='manual' "
                    "THEN 'manual' ELSE 'auto' END "
                    "WHERE folder_id=? AND (kind IS NULL OR kind='') "
                    "AND (ext IN ('.safetensors','.pt','.ckpt'))",
                    (fid,)
                )
        except Exception as e:
            log.warning(f"[Library] Post-add LoRA classification: {e}")
    lora_count = 0
    if scan_result:
        try:
            with db() as c:
                lora_count = c.execute(
                    "SELECT COUNT(*) FROM model_files WHERE folder_id=? AND kind='lora' AND missing=0",
                    (fid,)
                ).fetchone()[0]
        except Exception: pass
    return {
        "id": fid,
        "scan": {
            "count": scan_result["count"] if scan_result else 0,
            "lora_count": lora_count,
            "error": scan_result["error"] if scan_result else None,
        },
    }


def api_model_folder_remove(folder_id):
    with db() as c:
        c.execute("DELETE FROM model_folders WHERE id=?", (folder_id,))
    return {"ok": True}


def api_model_folder_toggle(folder_id, enabled):
    with db() as c:
        c.execute("UPDATE model_folders SET enabled=? WHERE id=?", (1 if enabled else 0, folder_id))
    return {"ok": True}


def api_model_folder_rescan(folder_id=None):
    """Relance le scan d'un dossier précis, ou de tous les dossiers actifs si folder_id est None."""
    results = []
    with db() as c:
        if folder_id:
            rows = c.execute("SELECT * FROM model_folders WHERE id=?", (folder_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM model_folders WHERE enabled=1").fetchall()
        for row in rows:
            res = model_catalog.rescan_folder(c, new_id, row)
            results.append({"folder_id": row["id"], "path": row["path"], **res})
            log.info(f"Model scan · {row['path']} · {res['count']} file(s)"
                     + (f" · error: {res['error']}" if res.get("error") else ""))
    return {"folders": results}


def api_model_files_list(kind=None, family=None, only_enabled_folders=True, include_missing=False):
    """Liste les fichiers modèles catalogués, filtrables par type/famille effective."""
    query = ("SELECT mf.*, mfo.path AS folder_path, mfo.enabled AS folder_enabled "
             "FROM model_files mf JOIN model_folders mfo ON mfo.id = mf.folder_id WHERE 1=1")
    params = []
    if only_enabled_folders:
        query += " AND mfo.enabled=1"
    if not include_missing:
        query += " AND mf.missing=0"
    if kind:
        query += " AND mf.kind=?"
        params.append(kind)
    if family:
        query += " AND mf.family=?"
        params.append(family)
    query += " ORDER BY mf.name COLLATE NOCASE ASC"
    with db() as c:
        rows = c.execute(query, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["size_human"] = model_catalog.format_size(d.get("size"))
        # Loader name expected by ComfyUI. Preserve subfolders when the scanned model
        # directory contains them (for example: Krea/model.safetensors).
        try:
            rel = os.path.relpath(d.get("path") or "", d.get("folder_path") or "")
            d["loader_name"] = rel.replace("\\", "/") if rel and not rel.startswith("..") else d.get("name")
        except (TypeError, ValueError):
            d["loader_name"] = d.get("name")
        # Champs de confort pour le frontend
        d["effective_kind"]   = d.get("kind")
        d["effective_family"] = d.get("family")
        d["has_manual_override"] = bool(d.get("manual_kind") or d.get("manual_family"))
        src = d.get("identification_source") or "auto"
        d["identification_source"] = src
        out.append(d)
    return out


def api_model_file_set_identification(file_id, manual_kind=None, manual_family=None, reset=False):
    """Pose (ou efface) un override manuel de type/famille sur un fichier modèle.
    La valeur effective (kind/family) est recalculée immédiatement."""
    with db() as c:
        row = c.execute("SELECT * FROM model_files WHERE id=?", (file_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Model file not found: {file_id}")
        if reset:
            mk, mf, src = None, None, "auto"
            eff_kind   = row["detected_kind"]   or row["kind"]
            eff_family = row["detected_family"] or row["family"]
        else:
            mk  = (manual_kind   or "").strip() or None
            mf  = (manual_family or "").strip() or None
            src = "manual" if (mk or mf) else "auto"
            eff_kind   = mk if mk else (row["detected_kind"]   or row["kind"])
            eff_family = mf if mf else (row["detected_family"] or row["family"])
        c.execute(
            "UPDATE model_files SET "
            "  manual_kind=?, manual_family=?, "
            "  kind=?, family=?, "
            "  identification_source=?, updated_at=? "
            "WHERE id=?",
            (mk, mf, eff_kind, eff_family, src, time.time(), file_id),
        )
    return {"ok": True, "id": file_id,
            "kind": eff_kind, "family": eff_family,
            "identification_source": src}



def api_models_enriched(kind=None, family=None):
    """Liste les fichiers modèles (tous sauf LoRA) enrichis de leur metadata Civitai.
    Réutilise intégralement lora_civitai_metadata — même table, même token, même cache."""
    query = (
        "SELECT mf.*, mfo.path AS folder_path, mfo.enabled AS folder_enabled, "
        "  lcm.civitai_model_id, lcm.civitai_model_version_id, "
        "  lcm.civitai_model_name, lcm.civitai_version_name, lcm.civitai_creator, "
        "  lcm.civitai_base_model, lcm.civitai_url, "
        "  lcm.civitai_preview_url, lcm.civitai_preview_path, "
        "  lcm.civitai_tags_json, lcm.civitai_match_status, "
        "  lcm.civitai_association_confirmed, lcm.identification_source AS civitai_source "
        "FROM model_files mf "
        "JOIN model_folders mfo ON mfo.id = mf.folder_id "
        "LEFT JOIN lora_civitai_metadata lcm ON lcm.model_file_id = mf.id "
        "WHERE mfo.enabled=1 AND mf.missing=0 AND mf.kind != 'lora' "
    )
    params = []
    if kind:
        query += " AND mf.kind=?"
        params.append(kind)
    if family:
        query += " AND mf.family=?"
        params.append(family)
    query += " ORDER BY mf.kind, mf.name COLLATE NOCASE ASC"
    with db() as c:
        rows = c.execute(query, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["size_human"] = model_catalog.format_size(d.get("size"))
        d["has_civitai"] = bool(d.get("civitai_model_id"))
        d["has_manual_civitai"] = (d.get("civitai_association_confirmed") == 1)
        # URL preview locale (même convention que LoRA)
        if d.get("civitai_preview_path"):
            d["preview_local_url"] = f"/lora_preview/civitai/{d['civitai_preview_path']}"
        else:
            d["preview_local_url"] = None
        out.append(d)
    return out


def api_civitai_dissociate(model_file_id: str) -> dict:
    """Supprime uniquement les métadonnées Civitai d'un fichier modèle (LoRA ou autre).
    Conserve : fichier local, identification manuelle, notes, cache preview local.
    Fonctionne pour toute entrée de lora_civitai_metadata via son model_file_id."""
    if not model_file_id:
        raise RuntimeError("model_Missing file_id.")
    with db() as c:
        row = c.execute(
            "SELECT id FROM model_files WHERE id=?", (model_file_id,)
        ).fetchone()
        if not row:
            raise RuntimeError(f"Model file not found: {model_file_id}")
        # Effacer uniquement les champs Civitai, conserver les corrections locales
        c.execute(
            "UPDATE lora_civitai_metadata SET "
            "  civitai_model_id=NULL, civitai_model_version_id=NULL, "
            "  civitai_model_name=NULL, civitai_version_name=NULL, "
            "  civitai_creator=NULL, civitai_base_model=NULL, "
            "  civitai_url=NULL, civitai_tags_json=NULL, "
            "  civitai_trigger_words_json=NULL, civitai_preview_url=NULL, "
            "  civitai_manual_url=NULL, civitai_association_confirmed=0, "
            "  civitai_match_status=NULL, civitai_last_sync=NULL, "
            "  civitai_last_error=NULL, identification_source='auto', "
            "  updated_at=? "
            "WHERE model_file_id=?",
            (time.time(), model_file_id)
        )
    log.info(f"[Civitai] Dissociation pour {model_file_id}")
    return {"ok": True}



# ─────────────────────────────────────────────────────────────────────────────
#  DOUBLONS LORA — analyse hash et dépublication
# ─────────────────────────────────────────────────────────────────────────────

_lora_dup_analysis: dict = {"running": False, "done": 0, "total": 0, "error": None}


def api_loras_analyze_duplicates() -> dict:
    """Lance l'analyse de doublons LoRA en arrière-plan (calcul SHA256 progressif).
    Ne recalcule pas si le hash est déjà en cache (chemin + taille + mtime inchangés)."""
    import threading as _threading

    if _lora_dup_analysis["running"]:
        return {"ok": False, "error": "Analysis already running."}

    with db() as c:
        loras = c.execute(
            "SELECT mf.id, mf.path, mf.size, mf.mtime "
            "FROM model_files mf "
            "WHERE mf.kind='lora' AND mf.missing=0 AND mf.path IS NOT NULL"
        ).fetchall()

    _lora_dup_analysis.update({"running": True, "done": 0, "total": len(loras), "error": None})

    def _run():
        try:
            for row in loras:
                mfid, fpath, fsize, fmtime = row["id"], row["path"], row["size"], row["mtime"]
                try:
                    _get_or_compute_hash(mfid, fpath, int(fsize or 0), float(fmtime or 0))
                except Exception as e:
                    log.warning(f"[DupLoRA] hash failed for {fpath}: {e}")
                _lora_dup_analysis["done"] += 1
        finally:
            _lora_dup_analysis["running"] = False

    _threading.Thread(target=_run, daemon=True, name="lora-dup-analysis").start()
    return {"ok": True, "total": len(loras)}


def api_loras_duplicates_list() -> dict:
    """Retourne les groupes de LoRA ayant le même hash SHA256 (doublons exacts).
    Chaque groupe désigne une copie principale (preferred_copy)."""
    with db() as c:
        # Groupes de hash avec au minimum 2 fichiers
        groups_raw = c.execute(
            "SELECT lcm.file_hash, GROUP_CONCAT(lcm.model_file_id, '|') AS ids "
            "FROM lora_civitai_metadata lcm "
            "JOIN model_files mf ON mf.id = lcm.model_file_id "
            "WHERE lcm.file_hash IS NOT NULL AND mf.kind='lora' AND mf.missing=0 "
            "GROUP BY lcm.file_hash HAVING COUNT(*) > 1"
        ).fetchall()
        groups = []
        for row in groups_raw:
            ids = row["ids"].split("|")
            files = []
            for fid in ids:
                mf = c.execute(
                    "SELECT mf.id, mf.name, mf.path, mf.size, mf.kind, "
                    "  lcm.file_hash, lcm.civitai_model_name "
                    "FROM model_files mf "
                    "LEFT JOIN lora_civitai_metadata lcm ON lcm.model_file_id=mf.id "
                    "WHERE mf.id=?", (fid,)
                ).fetchone()
                if mf:
                    files.append(dict(mf))
            if len(files) >= 2:
                # Copie principale : première par ordre alphabétique de chemin
                files.sort(key=lambda f: (f.get("path") or "").lower())
                groups.append({
                    "hash": row["file_hash"],
                    "count": len(files),
                    "primary": files[0],
                    "copies":  files[1:],
                })
    return {
        "groups": groups,
        "analysis": dict(_lora_dup_analysis),
    }


def api_loras_duplicates_status() -> dict:
    return dict(_lora_dup_analysis)


def api_model_wishlist_list():
    """Fiches Civitai ajoutées manuellement, sans fichier local installé."""
    with db() as c:
        rows = c.execute(
            "SELECT w.*, mf.name AS local_file_name, mf.id AS local_file_id "
            "FROM model_wishlist w "
            "LEFT JOIN model_files mf ON mf.id = w.local_match_file_id "
            "ORDER BY w.created_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["is_installed"] = bool(d.get("local_match_file_id") and d.get("local_file_name"))
        if d.get("civitai_preview_path"):
            d["preview_local_url"] = f"/lora_preview/civitai/{d['civitai_preview_path']}"
        else:
            d["preview_local_url"] = None
        out.append(d)
    return out


def api_model_wishlist_add(civitai_url: str, notes: str = "") -> dict:
    """Ajoute une fiche Civitai (modèle non installé) depuis une URL ou un ID."""
    if not civitai_url:
        raise RuntimeError("URL ou ID Civitai manquant.")
    data = api_civitai_fetch_by_url(civitai_url)
    if not data.get("civitai_model_id"):
        raise RuntimeError("Unable to retrieve Civitai information for this URL.")

    # Télécharger la preview
    preview_path = None
    preview_url = data.get("civitai_preview_url")
    wid = new_id()
    if preview_url:
        preview_path, _ = _civitai_cache_preview_image(preview_url, f"wl_{wid[:12]}")

    now = time.time()
    with db() as c:
        # Vérifie si déjà dans la wishlist (par civitai_model_version_id)
        vid = data.get("civitai_model_version_id")
        if vid:
            existing = c.execute(
                "SELECT id FROM model_wishlist WHERE civitai_model_version_id=?", (vid,)
            ).fetchone()
            if existing:
                raise RuntimeError(
                    f"This Civitai version is already in your list "
                    f"({data.get('civitai_model_name')}).")
        c.execute(
            "INSERT INTO model_wishlist("
            "  id, civitai_url, civitai_model_id, civitai_model_version_id, "
            "  civitai_model_name, civitai_version_name, civitai_creator, "
            "  civitai_base_model, civitai_preview_url, civitai_preview_path, "
            "  civitai_tags_json, kind, notes, created_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (wid,
             civitai_url,
             data.get("civitai_model_id"),
             data.get("civitai_model_version_id"),
             data.get("civitai_model_name"),
             data.get("civitai_version_name"),
             data.get("civitai_creator"),
             data.get("civitai_base_model"),
             preview_url, preview_path,
             json.dumps(data.get("civitai_tags", []), ensure_ascii=False),
             data.get("model_type", "").lower() or None,
             (notes or "").strip() or None,
             now, now),
        )
    return {"ok": True, "id": wid, "name": data.get("civitai_model_name")}


def api_model_wishlist_remove(wishlist_id: str) -> dict:
    """Supprime une fiche non-installée de la wishlist."""
    with db() as c:
        row = c.execute("SELECT id FROM model_wishlist WHERE id=?", (wishlist_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Card not found: {wishlist_id}")
        c.execute("DELETE FROM model_wishlist WHERE id=?", (wishlist_id,))
    return {"ok": True}


def api_model_wishlist_check(wishlist_id: str) -> dict:
    """Vérifie si un fichier local correspondant à une fiche wishlist est maintenant installé.
    Cherche par nom de fichier ou civitai_model_version_id dans model_files."""
    with db() as c:
        w = c.execute("SELECT * FROM model_wishlist WHERE id=?", (wishlist_id,)).fetchone()
        if not w:
            raise RuntimeError(f"Card not found: {wishlist_id}")
        w = dict(w)

        # Chercher par version_id dans lora_civitai_metadata
        found_file_id = None
        if w.get("civitai_model_version_id"):
            row = c.execute(
                "SELECT model_file_id FROM lora_civitai_metadata "
                "WHERE civitai_model_version_id=?",
                (w["civitai_model_version_id"],)
            ).fetchone()
            if row:
                found_file_id = row[0]

        if found_file_id:
            c.execute(
                "UPDATE model_wishlist SET local_match_file_id=?, updated_at=? WHERE id=?",
                (found_file_id, time.time(), wishlist_id)
            )
            mf = c.execute("SELECT name FROM model_files WHERE id=?", (found_file_id,)).fetchone()
            return {"ok": True, "installed": True,
                    "local_file_id": found_file_id,
                    "local_file_name": mf["name"] if mf else None}
    return {"ok": True, "installed": False}



def api_model_file_delete(file_id: str) -> dict:
    """Supprime une fiche du catalogue (model_files) sans toucher au fichier disque.
    Supprime aussi les métadonnées Civitai associées."""
    if not file_id:
        raise RuntimeError("Missing file_id.")
    with db() as c:
        row = c.execute("SELECT name FROM model_files WHERE id=?", (file_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Card not found: {file_id}")
        # Supprimer métadonnées Civitai
        c.execute("DELETE FROM lora_civitai_metadata WHERE model_file_id=?", (file_id,))
        # Supprimer la fiche catalogue
        c.execute("DELETE FROM model_files WHERE id=?", (file_id,))
    log.info(f"[Library] Card removed from catalog: {row['name']} ({file_id})")
    return {"ok": True, "name": row["name"]}


def api_model_file_delete_batch(ids: list) -> dict:
    """Supprime plusieurs fiches du catalogue en une passe."""
    if not ids:
        return {"ok": False, "error": "No ID provided.", "deleted": 0}
    deleted, errors = 0, []
    for fid in ids:
        try:
            api_model_file_delete(fid)
            deleted += 1
        except Exception as e:
            errors.append({"id": fid, "error": str(e)})
    return {"ok": True, "deleted": deleted, "errors": errors}


def api_model_catalog_summary():
    """Compte les modèles par type, pour affichage rapide (section 2 : 'nombre de modèles détectés')."""
    with db() as c:
        rows = c.execute(
            "SELECT mf.kind, COUNT(*) AS n FROM model_files mf "
            "JOIN model_folders mfo ON mfo.id = mf.folder_id "
            "WHERE mfo.enabled=1 AND mf.missing=0 GROUP BY mf.kind").fetchall()
    return {r["kind"] or "unknown": r["n"] for r in rows}


def api_scenario_generate(data, settings):
    """Génère un scénario complet via le LLM à partir des champs fournis."""
    place = data.get("place", "")
    mood_theme = data.get("mood_theme", "")
    theme = data.get("theme", "")
    relationship = data.get("relationship", "")
    sysmsg = (
        "You create a roleplay / visual novel scenario. "
        "Using the provided elements, generate a short immersive scenario. "
        "Reply ONLY with valid JSON, keys: "
        '"title", "place", "mood_theme", "theme", "relationship", "goal", "conflict", "notes". '
        '"notes" : paragraphe d\'ambiance de 2-3 phrases (accroche narrative). '
        "Use the provided values and invent missing ones coherently."
    )
    user = (f"Place: {place or 'your choice'}\n"
            f"Mood: {mood_theme or 'your choice'}\n"
            f"Theme: {theme or 'your choice'}\n"
            f"Relationship: {relationship or 'your choice'}")
    raw = llm_util_chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": user}],
                   settings, max_tokens=400, temperature=0.9)
    parsed = _extract_json(raw)
    return api_scenario_save(parsed)


def api_scenario_apply(chat_id, scenario_id):
    """Injecte un scénario dans une conversation (stocke scenario_id, injecté dans le sys prompt)."""
    with db() as c:
        c.execute("UPDATE chats SET scenario_id=? WHERE id=?", (scenario_id, chat_id))
    return {"ok": True, "scenario_id": scenario_id}


def get_scenario_block(chat_id):
    """Renvoie le bloc scénario à injecter dans le system prompt si un scénario est actif."""
    with db() as c:
        chat = c.execute("SELECT scenario_id FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat or not chat["scenario_id"]:
            return ""
        sc = c.execute("SELECT * FROM scenarios WHERE id=?", (chat["scenario_id"],)).fetchone()
    if not sc:
        return ""
    sc = dict(sc)
    parts = []
    if sc.get("place"):       parts.append(f"Place: {sc['place']}")
    if sc.get("mood_theme"):  parts.append(f"Mood: {sc['mood_theme']}")
    if sc.get("theme"):       parts.append(f"Theme: {sc['theme']}")
    if sc.get("relationship"):  parts.append(f"Relationship: {sc['relationship']}")
    if sc.get("goal"):        parts.append(f"Goal: {sc['goal']}")
    if sc.get("conflict"):    parts.append(f"Conflict: {sc['conflict']}")
    header = "\n".join(f"- {p}" for p in parts)
    notes = sc.get("notes", "")
    return f"\n\n[Active scenario]\n{header}" + (f"\n{notes}" if notes else "")


def get_mood_block(character_id):
    """Bloc d'humeur injecté dans le system prompt (stats + style de ton)."""
    state = get_char_mood(character_id)
    mood = state.get("mood", "neutral")
    emotion = MOOD_TO_EMOTION.get(mood, "calm")
    tone = EMOTION_TONE.get(emotion, EMOTION_TONE["calm"])
    stats_line = (f"affection={state.get('affection',50)}, trust={state.get('trust',50)}, "
                  f"energy={state.get('energy',70)}, curiosity={state.get('curiosity',60)}, "
                  f"stress={state.get('stress',10)}")
    return (f"\n\n[Emotional state: {emotion.upper()} (mood={mood}) — {stats_line}]\n"
            f"Adapt your style: {tone}")


def compose_canonical_profile_prompt(char):
    """Prompt canonique de creation d'avatar : cadrage hanches-tete, studio neutre,
    silhouette visible. Sert de reference principale I2I : doit montrer clairement
    visage, cheveux, epaules, torse, taille, hanches et silhouette generale.
    Ne pas utiliser pour les variantes post-creation (libres)."""
    locked = (char.get("locked_tags") or "").strip() or "Consistent character identity."
    return (
        f"Fixed character identity:\n"
        f"{locked}. These physical traits must remain consistent and must not change.\n\n"
        f"Pose and action:\n"
        f"Standing upright in a relaxed natural posture, arms visible when possible.\n\n"
        f"Framing:\n"
        f"Hips-up portrait, from hips to head, centered composition, front-facing or slight "
        f"three-quarter view.\n\n"
        f"Expression:\n"
        f"Calm natural expression, looking toward the camera.\n\n"
        f"Outfit:\n"
        f"Fully clothed, simple fitted everyday clothing appropriate to the character, "
        f"clearly showing the body silhouette.\n\n"
        f"Environment:\n"
        f"Simple clean studio background.\n\n"
        f"Lighting:\n"
        f"Balanced soft studio lighting.\n\n"
        f"Mood:\n"
        f"Neutral, clear character reference atmosphere."
    )


def api_avatar_generate(character_id, keep_seed=False, variant="", prompt=None, dry_run=False,
                        canonical_profile=False):
    """Genere un avatar T2I, traits verrouilles garantis. variant = cle de VARIANT_TAGS.
    canonical_profile=True : cadrage hanches->tete, studio neutre (premiere generation et rerolls creation).
    dry_run renvoie le prompt propose ; prompt!=None l'utilise tel quel."""
    settings = get_settings()
    with db() as c:
        char = c.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
    if not char:
        raise RuntimeError("Character not found (save it first).")
    char = dict(char)
    krea_active = (settings.get("image_family") or "").strip() == "krea2"
    if prompt is None:
        if krea_active:
            # Krea 2 : prompts descriptifs littéraux dédiés (jamais le template Flux)
            token = (char.get("krea_token") or "").strip()
            phys  = _krea_physical_base(char)
            if canonical_profile or not (char.get("avatar") or "").strip():
                prompt = krea_prompt_builder.build_krea_canonical_prompt(
                    identity_token=token,
                    physical_description=phys,
                    force_physical=_krea_force_physical(char),
                )
            else:
                extra = VARIANT_TAGS.get(variant, "")
                scene = extra or "a natural relaxed portrait"
                prompt = build_krea_chat_prompt(scene, settings, char)
        elif canonical_profile or not (char.get("avatar") or "").strip():
            # Premiere generation ou reroll canonique : cadrage hanches->tete
            prompt = compose_canonical_profile_prompt(char)
        else:
            extra = VARIANT_TAGS.get(variant, "")
            prompt = compose_image_prompt(char, extra=extra)
    if dry_run:
        return {"prompt": prompt}
    seed = char.get("last_seed") if (keep_seed and char.get("last_seed") is not None) else None
    if krea_active:
        img, used_seed = generate_t2i(prompt, settings, seed=seed, family="krea2")
    else:
        img, used_seed = generate_t2i(prompt, settings, seed=seed)
    with db() as c:
        c.execute("UPDATE characters SET last_seed=? WHERE id=?", (used_seed, character_id))
        c.execute("INSERT INTO gallery(id, character_id, image, prompt, seed, created_at) VALUES (?,?,?,?,?,?)",
                  (new_id(), character_id, img, prompt, used_seed, time.time()))
        # Si le personnage n'a pas encore d'avatar principal, on definit celui-ci
        # (garantit que l'illustration en chat utilisera bien l'I2I avec reference).
        if not (char.get("avatar") or "").strip():
            c.execute("UPDATE characters SET avatar=? WHERE id=?", (img, character_id))
            auto_main = True
        else:
            auto_main = False
    return {"image": img, "seed": used_seed, "prompt": prompt, "auto_main": auto_main}


def api_set_main_avatar(character_id, image):
    with db() as c:
        c.execute("UPDATE characters SET avatar=? WHERE id=?", (image, character_id))
    return {"ok": True}


# --------------------------------------------------------------------------- #
#  Apercus visuels des options du configurateur (style candy.ai)
# --------------------------------------------------------------------------- #
PREVIEW_SEED_FIXED = 42   # seed fixe pour corps/poitrine/hanches (comparaison coherente)
PREVIEW_SEED_FIELDS = {"corps", "poitrine", "hanches"}  # champs qui beneficient du seed fixe

PREVIEW_NEG = ("low quality, blurry, deformed, bad anatomy, extra limbs, fused fingers, "
               "watermark, text, logo, child, minor, underage, teen")
_GENDER_NOUN = {"female": "woman", "transfemale": "woman", "male": "man", "transmale": "man"}

# Poitrine cote femme (tailles bien distinctes) et cote homme (torse)
_FEMALE_CHEST = {
    "flat": "a completely flat chest", "small": "small A-cup breasts",
    "medium": "medium C-cup breasts", "large": "large D-cup breasts",
    "full": "very large full DD-cup breasts", "broad": "a broad chest",
    "defined": "a toned athletic chest",
}
_MALE_CHEST = {
    "flat": "a flat lean chest", "small": "a slim chest", "medium": "an average chest",
    "large": "a large muscular chest", "full": "a full broad chest",
    "broad": "a broad muscular chest", "defined": "a chiseled defined chest",
}
_HIPS = {
    "flat": "flat narrow hips", "small": "small hips", "medium": "medium hips and butt",
    "round": "round full butt", "large": "large hips and big butt",
    "wide": "very wide hips", "curvy": "curvy wide hips and round butt",
}


def _gender_noun(gender):
    return _GENDER_NOUN.get(gender, "person")


def _en_phrase(field, value):
    """Retourne le tag image anglais d'une valeur de configurateur, ou la valeur brute."""
    entry = CONFIG_MAP.get(field, {}).get(value)
    if not entry:
        return value
    # CONFIG_MAP v38.0.1 : {"fr": ..., "en": ..., "image_tag": ...}
    return entry.get("image_tag") or entry.get("en") or value


def _preview_prompt(field, value, gender=""):
    """Prompt d'apercu 512x512 en anglais, adapte au genre choisi. Nudite autorisee (adultes)."""
    noun = _gender_noun(gender)
    base = ("professional photo, neutral light gray studio background, soft even lighting, "
            "sharp focus, adult, 25 years old")
    if field == "genre":
        subj = f"a portrait of {_en_phrase('genre', value)}, head and shoulders"
    elif field == "origine":
        subj = f"a portrait of a {_en_phrase('origine', value)} {noun}, head and shoulders, natural skin tone"
    elif field == "corps":
        subj = f"a full body photo of a {noun} with {_en_phrase('corps', value)}, wearing fitted underwear"
    elif field == "poitrine":
        if noun == "man":
            subj = f"a man with {_MALE_CHEST.get(value, value)}, bare chest, upper body, front view"
        else:
            subj = (f"an adult {noun} with {_FEMALE_CHEST.get(value, value)}, topless, upper body, "
                    "front view, accurate realistic breast size")
    elif field == "hanches":
        subj = (f"a {noun} with {_HIPS.get(value, value)}, lower body, rear three-quarter view, "
                "wearing a thong")
    elif field == "cheveux_couleur":
        subj = f"a portrait of a {noun} with {_en_phrase('cheveux_couleur', value)}, hair clearly visible, head and shoulders"
    elif field == "coiffure":
        subj = f"a portrait of a {noun} with a {_en_phrase('coiffure', value)} hairstyle, hair clearly visible, head and shoulders"
    else:
        subj = value
    return f"{base}, {subj}"


def api_config_preview(field, value, gender="", regen=False):
    """Generate (or return) a configurator preview, cached per image family."""
    field = (field or "").strip()
    value = (value or "").strip()
    gender = (gender or "").strip()
    if field == "genre":
        gender = ""           # the gender preview does not depend on another gender
    if not field or not value:
        raise RuntimeError("Missing field or value.")
    settings = get_settings()
    preview_family = (settings.get("image_family") or "flux2_klein").strip()
    with db() as c:
        row = c.execute(
            "SELECT image FROM option_previews WHERE field=? AND value=? AND gender=? AND family=?",
            (field, value, gender, preview_family),
        ).fetchone()
    if row and not regen:
        return {"field": field, "value": value, "gender": gender,
                "family": preview_family, "image": row["image"], "cached": True}
    prompt = _preview_prompt(field, value, gender)
    # seed fixe pour les champs de morphologie : assure la meme base pour comparer
    fixed_seed = PREVIEW_SEED_FIXED if field in PREVIEW_SEED_FIELDS else None
    if (settings.get("image_family") or "").strip() == "krea2":
        # Krea 2 : MÊME workflow unifié, réglages allégés (steps réduits, 512x512).
        # Aucun LoRA injecté pour les aperçus d'options (neutralité des templates).
        preview_settings = _krea_preview_settings(settings, clear_loras=True)
        img, _seed = generate_t2i(prompt, preview_settings, negative=PREVIEW_NEG,
                                  seed=fixed_seed, workflow=model_manifests.KREA2_WORKFLOW,
                                  family="krea2")
    else:
        img, _seed = generate_t2i(prompt, settings, negative=PREVIEW_NEG,
                                  seed=fixed_seed, workflow="preview.json")
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO option_previews(field, value, gender, family, image, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (field, value, gender, preview_family, img, time.time()),
        )
    return {"field": field, "value": value, "gender": gender,
            "family": preview_family, "image": img, "cached": False}


def api_config_previews():
    """Return cached configurator previews for the currently selected image family."""
    family = (get_settings().get("image_family") or "flux2_klein").strip()
    with db() as c:
        rows = c.execute(
            "SELECT field, value, gender, image FROM option_previews WHERE family=?",
            (family,),
        ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["field"], {}).setdefault(r["gender"] or "", {})[r["value"]] = r["image"]
    return out


def api_regenerate_text(message_id):
    """Regenere le texte d'un message (correction du LLM). Reprend le contexte de la conversation."""
    settings = get_settings()
    with db() as c:
        msg = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not msg:
            raise RuntimeError("Message not found.")
        msg = dict(msg)
        char = None
        if msg.get("character_id"):
            row = c.execute("SELECT * FROM characters WHERE id=?", (msg["character_id"],)).fetchone()
            char = dict(row) if row else None
        # Contexte : messages precedents du meme chat (dernier systeme inclus)
        history = c.execute(
            "SELECT role, character_id, content FROM messages "
            "WHERE chat_id=? AND id != ? ORDER BY created_at",
            (msg["chat_id"], message_id)).fetchall()
    # Reconstruire les messages pour le LLM
    sys_parts = []
    if char:
        sys_parts.append(char.get("system_prompt") or "")
        sys_parts.append(get_memory_block(char["id"]))
        sys_parts.append(get_persona_block(settings))
    messages = [{"role": "system", "content": "\n\n".join(p for p in sys_parts if p)}] if sys_parts else []
    for h in history:
        role = "assistant" if h["role"] == "assistant" else "user"
        messages.append({"role": role, "content": h["content"] or ""})
    # On ajoute l'invite de regeneration
    messages.append({"role": "user", "content":
        "[Regenere ta derniere replique differemment, meme sens mais formulation nouvelle, "
        "sans mentionner cette instruction.]"})
    new_text = llm_chat(messages, settings, max_tokens=800, temperature=0.9).strip()
    if not new_text:
        raise RuntimeError("Le LLM n'a pas produit de texte.")
    with db() as c:
        c.execute("UPDATE messages SET content=? WHERE id=?", (new_text, message_id))
    return {"content": new_text}


def api_continue_message(message_id):
    """Continue la reponse d'un message assistant sans la remplacer ni repeter son contenu.
    Ajoute un NOUVEAU message assistant dans la conversation, avec la meme voix/personnage.
    Ne modifie pas l'humeur, la memoire, l'image, la seed ou l'avatar."""
    settings = get_settings()
    with db() as c:
        msg = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not msg:
            raise RuntimeError("Message not found.")
        msg = dict(msg)
        if msg.get("role") != "assistant":
            raise RuntimeError("Seul un message assistant peut etre prolonge.")
        # Verifier que c'est bien le dernier message assistant de cette conversation
        last_assistant = c.execute(
            "SELECT id FROM messages WHERE chat_id=? AND role='assistant' "
            "ORDER BY created_at DESC LIMIT 1", (msg["chat_id"],)).fetchone()
        if not last_assistant or last_assistant["id"] != message_id:
            raise RuntimeError("Ce message n'est plus le dernier message assistant de la conversation.")
        chat = c.execute("SELECT * FROM chats WHERE id=?", (msg["chat_id"],)).fetchone()
        char = None
        if msg.get("character_id"):
            row = c.execute("SELECT * FROM characters WHERE id=?", (msg["character_id"],)).fetchone()
            char = dict(row) if row else None
        # Historique complet du chat jusqu'au message inclus
        history = c.execute(
            "SELECT role, character_id, content FROM messages "
            "WHERE chat_id=? ORDER BY created_at",
            (msg["chat_id"],)).fetchall()

    members = _active_members(msg["chat_id"])
    is_group = bool(chat and chat["is_group"])

    # Construction du prompt système (même logique que _respond, sans injection memory/mood)
    sys_parts = []
    if char:
        sys_parts.append(char.get("system_prompt") or "")
        sys_parts.append(get_memory_block(char["id"]))
        sys_parts.append(get_persona_block(settings))
    # Instruction de continuation : jamais visible dans la memoire ni les logs utilisateur
    CONTINUE_INSTRUCTION = (
        "Continue exactly from your previous answer. Do not repeat anything already said. "
        "Continue naturally from the unfinished thought, keeping the same tone, character, "
        "language and formatting."
    )
    sys_parts.append("\n" + CONTINUE_INSTRUCTION)

    messages_llm = [{"role": "system", "content": "\n\n".join(p for p in sys_parts if p)}]
    for h in history:
        role = "assistant" if h["role"] == "assistant" else "user"
        messages_llm.append({"role": role, "content": h["content"] or ""})

    distribution = context_manager.get_context_distribution(settings)
    new_text = llm_chat(messages_llm, settings,
                        max_tokens=distribution["response_max_tokens"]).strip()
    if not new_text:
        raise RuntimeError("Le LLM n'a pas produit de suite.")
    new_text = _clean_roleplay_reply(new_text, char.get("name") or "" if char else "")

    new_id_ = new_id()
    with db() as c:
        c.execute(
            "INSERT INTO messages(id, chat_id, role, character_id, content, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (new_id_, msg["chat_id"], "assistant", msg.get("character_id"), new_text, time.time()),
        )
    return {"id": new_id_, "character_id": msg.get("character_id"), "content": new_text}


def api_generate_background(chat_id, message_id, prompt=None, dry_run=False):
    """Genere un fond (T2I 1024x1024) pour une scene, sans personnage.
    Peut etre reutilise comme 4e reference dans un groupe de 3."""
    settings = get_settings()
    with db() as c:
        msg = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not msg:
            raise RuntimeError("Message not found.")
    msg = dict(msg)
    if prompt is None:
        # Prompt de fond : decor, ambiance, sans personnage
        image_model_name = "Krea 2" if (settings.get("image_family") or "") == "krea2" else "FLUX.2"
        sysmsg = ("You describe an interior or exterior scene (background only, no people) "
                  f"in natural English for the {image_model_name} image model. One sentence, vivid, cinematic. "
                  "Describe only the setting, lighting and mood — no characters.")
        messages = [{"role": "system", "content": sysmsg},
                    {"role": "user", "content": msg["content"]}]
        prompt = llm_util_chat(messages, settings, max_tokens=100, temperature=0.7).strip()
    if dry_run:
        return {"prompt": prompt}
    img, used_seed = generate_t2i(prompt, settings)
    # On stocke ce fond dans la galerie du 1er personnage de la conversation
    with db() as c:
        members = c.execute(
            "SELECT character_id FROM chat_members WHERE chat_id=? LIMIT 1", (chat_id,)).fetchone()
        cid = members["character_id"] if members else None
        if cid:
            c.execute("INSERT INTO gallery(id, character_id, image, prompt, seed, created_at) "
                      "VALUES (?,?,?,?,?,?)", (new_id(), cid, img, prompt, used_seed, time.time()))
    return {"image": img, "prompt": prompt, "seed": used_seed, "type": "background"}
    """Ajoute un personnage a une conversation (la passe en groupe si >1 membre)."""
    if not chat_id or not character_id:
        raise RuntimeError("Conversation ou personnage manquant.")
    with db() as c:
        c.execute("INSERT OR IGNORE INTO chat_members(chat_id, character_id, active) VALUES (?,?,1)",
                  (chat_id, character_id))
        n = c.execute("SELECT COUNT(*) AS n FROM chat_members WHERE chat_id=?", (chat_id,)).fetchone()["n"]
        if n > 1:
            c.execute("UPDATE chats SET is_group=1 WHERE id=?", (chat_id,))
    return {"ok": True, "members": n, "is_group": n > 1}


# --------------------------------------------------------------------------- #
#  Sauvegarde / export JSON
# --------------------------------------------------------------------------- #
def api_export_character(character_id, with_history=True):
    with db() as c:
        char = c.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
        if not char:
            raise RuntimeError("Character not found.")
        mem = c.execute("SELECT kind, content, created_at FROM memory WHERE character_id=?",
                        (character_id,)).fetchall()
        gal = c.execute("SELECT image, prompt, seed, created_at FROM gallery WHERE character_id=?",
                        (character_id,)).fetchall()
        export = {"character": dict(char), "memory": [dict(m) for m in mem],
                  "gallery": [dict(g) for g in gal], "exported_at": time.time()}
        if with_history:
            chats = c.execute(
                "SELECT DISTINCT ch.id, ch.title, ch.is_group FROM chats ch "
                "JOIN chat_members cm ON cm.chat_id=ch.id WHERE cm.character_id=?",
                (character_id,)).fetchall()
            hist = []
            for ch in chats:
                msgs = c.execute(
                    "SELECT role, character_id, content, image, created_at FROM messages "
                    "WHERE chat_id=? ORDER BY created_at ASC", (ch["id"],)).fetchall()
                hist.append({"chat": dict(ch), "messages": [dict(m) for m in msgs]})
            export["history"] = hist
    return export


def api_import_character(data):
    ch = dict(data.get("character", {}))
    ch.pop("created_at", None)
    ch.pop("id", None)   # toujours un nouveau personnage : evite d'ecraser un perso existant par collision d'id
    saved = api_character_save(ch)
    cid = saved["id"]
    with db() as c:
        for m in data.get("memory", []):
            c.execute("INSERT INTO memory(id, character_id, kind, content, created_at) VALUES (?,?,?,?,?)",
                      (new_id(), cid, m.get("kind", "long"), m.get("content", ""), time.time()))
    return saved


# --------------------------------------------------------------------------- #
#  Studio Image — familles de workflow, compatibilité, sélection de modèles
#  (sections 1 et 3 du cahier des charges "gestion locale des modèles")
# --------------------------------------------------------------------------- #
def api_image_families():
    """Liste des familles de workflow avec leurs composants déclarés (pour le menu
    'Famille de workflow' qui met à jour les sélecteurs visibles)."""
    return model_manifests.list_families()


def api_image_workflows(family_id=None):
    """Workflows disponibles, filtrés par famille si fournie. Vérifie l'existence réelle
    du fichier sur disque (un workflow déclaré mais absent est signalé, pas masqué)."""
    reg = model_manifests.workflows_for_family(family_id) if family_id else model_manifests.WORKFLOW_REGISTRY
    out = []
    for rel_path, manifest in reg.items():
        full = os.path.join(WF_DIR, rel_path)
        out.append({"file": rel_path, **manifest, "exists": os.path.exists(full)})
    return out


def _component_value(settings, component):
    """Valeur actuellement choisie pour un composant (chemin du reglage declare dans le manifeste)."""
    key = component["setting"]
    val = settings.get(key, "")
    if component.get("multi"):
        try:
            return json.loads(val) if val else []
        except Exception:
            return []
    return val


def api_image_compatibility(family_id, settings=None):
    """Vérifie la complétude des composants requis pour une famille.
    Pour flux2_klein : validation mode-aware — seul le composant UNet du mode actif
    (gguf ou safetensors) est obligatoire. Retourne également mode, active_unet et
    flux2_summary pour l'affichage Studio."""
    settings = settings or get_settings()
    family = model_manifests.get_family(family_id)
    if not family:
        return {"family": family_id, "ok": False, "error": f"Famille unknowne : {family_id}",
                "components": []}

    # Mode actif Flux 2 Klein
    flux2_mode = settings.get("flux2_loader_mode", "gguf").strip() if family_id == "flux2_klein" else None

    comps_status = []
    all_ok = True
    for comp in family["components"]:
        val = _component_value(settings, comp)
        is_multi = comp.get("multi", False)
        comp_mode = comp.get("mode")  # "gguf" | "safetensors" | None

        # Pour flux2_klein : le composant UNet n'est obligatoire que si son mode est le mode actif
        if family_id == "flux2_klein" and comp_mode is not None:
            required = (comp_mode == flux2_mode)
        else:
            required = comp["required"]

        filled = bool(val) if not is_multi else True
        if required and not is_multi and not filled:
            all_ok = False

        status = {
            "kind": comp["kind"], "label": comp["label"],
            "required": required, "active_mode": (comp_mode == flux2_mode) if comp_mode else None,
            "setting": comp["setting"], "value": val, "filled": filled,
            "ext": comp.get("ext"),   # ".gguf" | ".safetensors" | None — pour filtrage JS
            "comp_mode": comp_mode,   # "gguf" | "safetensors" | None
        }
        if filled and not is_multi and isinstance(val, str):
            val_base = val.replace("\\", "/").rsplit("/", 1)[-1]
            with db() as c:
                row = c.execute(
                    "SELECT 1 FROM model_files WHERE name=? AND missing=0 LIMIT 1",
                    (val_base,),
                ).fetchone()
            status["found_in_catalog"] = bool(row)
        comps_status.append(status)

    # Récapitulatif Flux 2 Klein pour l'UI Studio
    flux2_summary = None
    if family_id == "flux2_klein":
        if flux2_mode == "safetensors":
            active_unet = settings.get("img_unet_safetensors", "").strip()
            # Résoudre le workflow effectif de référence (t2i)
            try:
                wf_eff = resolve_flux2_workflow_variant("t2i.json", settings)
            except Exception:
                wf_eff = "t2i_st.json (not configured)"
        else:
            active_unet = (settings.get("img_unet_gguf") or settings.get("img_unet") or "").strip()
            try:
                wf_eff = resolve_flux2_workflow_variant("t2i.json", settings)
            except Exception:
                wf_eff = "t2i.json (not configured)"
        flux2_summary = {
            "mode": flux2_mode,
            "mode_label": "Safetensors" if flux2_mode == "safetensors" else "GGUF",
            "active_unet": active_unet or "(not configured)",
            "workflow_example": wf_eff,
        }

    return {"family": family_id, "label": family["label"], "is_video": family.get("is_video", False),
            "ok": all_ok, "components": comps_status,
            "flux2_mode": flux2_mode, "flux2_summary": flux2_summary}


def api_image_generate(family_id, workflow_file, prompt, negative=None, seed=None, images=None):
    """Point d'entrée Studio Image : vérifie la compatibilité (section 3, ne génère jamais
    si un composant requis manque), puis lance la génération via le moteur existant.
    images : liste de noms de fichiers (déjà dans data/images, via /api/upload) à utiliser
    comme références — le nombre attendu est déclaré par le manifeste du workflow (refs)."""
    settings = get_settings()
    global_family = (settings.get("image_family") or "flux2_klein").strip()
    if family_id != global_family:
        raise RuntimeError(
            f"The global image engine is {global_family}, not {family_id}. "
            "Refresh Image Studio after changing the global selector."
        )
    compat = api_image_compatibility(global_family, settings)
    if not compat["ok"]:
        missing = [c["label"] for c in compat["components"] if c["required"] and not c["filled"]]
        raise RuntimeError(
            "Generation impossible: missing component(s) for " + compat["label"] + " — "
            + ", ".join(missing) + ". Select them in Image Studio before generating."
        )
    # Flux 2 Klein : résoudre le variant workflow (gguf ↔ safetensors) avant toute génération.
    # generate_t2i/i2i/group reçoivent le workflow déjà résolu → pas de bypass silencieux.
    if family_id == "flux2_klein" and workflow_file:
        workflow_file = resolve_flux2_workflow_variant(workflow_file, settings)

    manifest = model_manifests.get_workflow_manifest(workflow_file)
    if manifest and manifest["family"] != family_id:
        raise RuntimeError(f"Workflow {workflow_file} belongs to family "
                           f"{manifest['family']}, not {family_id}.")

    n_refs = (manifest or {}).get("refs", 0)
    images = [i for i in (images or []) if i]
    if n_refs > 0 and len(images) < n_refs:
        raise RuntimeError(
            f"This workflow expects {n_refs} reference image(s) ({len(images)} provided). "
            "Import the required images before generating."
        )

    if n_refs == 0:
        img, used_seed = generate_t2i(prompt, settings, negative=negative, seed=seed,
                                      workflow=workflow_file, family=family_id)
    elif n_refs == 1:
        img, used_seed = generate_i2i(prompt, images[0], settings, negative=negative, seed=seed,
                                      workflow=workflow_file, family=family_id)
    else:
        img, used_seed = generate_group(prompt, images[:n_refs], settings, negative=negative,
                                        seed=seed, workflow=workflow_file, family=family_id)

    # Chaque image generee depuis Studio Image est automatiquement sauvegardee dans la Galerie,
    # meme sans personnage associe (character_id=NULL) : aucune image Studio ne doit etre perdue.
    gallery_id = new_id()
    with db() as c:
        c.execute(
            "INSERT INTO gallery(id, character_id, image, prompt, seed, source, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (gallery_id, None, img, prompt, used_seed, "studio", time.time()),
        )

    return {"image": img, "seed": used_seed, "gallery_id": gallery_id, "source": "studio"}


def api_image_set_component(family_id, kind_or_setting, value):
    """Applique le modèle choisi pour un composant. N'écrase jamais un autre réglage que
    celui déclaré dans le manifeste (section 1 : on ne réécrit que les valeurs prévues)."""
    family = model_manifests.get_family(family_id)
    if not family:
        raise RuntimeError(f"Famille unknowne : {family_id}")
    comp = next((c for c in family["components"]
                if c["setting"] == kind_or_setting or c["kind"] == kind_or_setting), None)
    if not comp:
        raise RuntimeError(f"Composant '{kind_or_setting}' not declared for family {family_id}.")
    key = comp["setting"]
    if comp.get("multi"):
        if not isinstance(value, list):
            raise RuntimeError("Ce composant accepte une liste de valeurs (LoRA multiples).")
        save_settings({key: json.dumps(value, ensure_ascii=False)})
    else:
        save_settings({key: value or ""})
    return {"ok": True, "setting": key}


# --------------------------------------------------------------------------- #
#  Catalogue LLM unifié (section 4 du cahier des charges)
#  GGUF et Safetensors ne sont jamais traités comme interchangeables : chaque
#  entree du catalogue connait son format reel et les backends qui le supportent.
# --------------------------------------------------------------------------- #
def api_llm_backends_list():
    settings = get_settings()
    backend = llm_backends.list_backends()[0]
    return [{**backend, "status": llm_backends.probe_lmstudio(settings)}]


def api_llm_backend_status(backend_id="lmstudio"):
    return llm_backends.probe_lmstudio(get_settings())


def api_llm_catalog():
    """Return models exposed by LM Studio. Local GGUF discovery is intentionally disabled."""
    settings = get_settings()
    probe = llm_backends.probe_lmstudio(settings)
    entries = []
    configured = (settings.get("lmstudio_model") or "").strip()
    for item in probe.get("models", []):
        model_id = item.get("id") if isinstance(item, dict) else str(item)
        if not model_id:
            continue
        entries.append({
            "name": model_id,
            "id": model_id,
            "format": "lmstudio",
            "valid": True,
            "compatible_backends": ["lmstudio"],
            "backend_compatible": True,
            "status": "ready",
            "is_configured": model_id == configured,
        })
    return {
        "entries": entries,
        "current_backend": "lmstudio",
        "reachable": bool(probe.get("reachable")),
        "error": probe.get("error"),
    }


def api_llm_validate_path(path):
    """Legacy endpoint kept for old clients; AmiorAI no longer loads local model files."""
    return {
        "valid": False,
        "backend": "lmstudio",
        "error": "Local LLM file loading was removed. Load the model in LM Studio instead.",
    }

def api_llm_util_status():
    """Status of the optional utility model on the same LM Studio server."""
    settings = get_settings()
    enabled = str(settings.get("llm_util_enabled", "false")).lower() in ("true", "1", "yes")
    probe = llm_backends.probe_lmstudio(settings)
    model = (settings.get("llm_util_model") or settings.get("lmstudio_model") or "").strip()
    model_ids = [m.get("id") for m in probe.get("models", []) if isinstance(m, dict) and m.get("id")]
    return {
        "enabled": enabled,
        "url": settings.get("lmstudio_url"),
        "model": model,
        "reachable": bool(probe.get("reachable")),
        "models": model_ids,
        "error": None if enabled and probe.get("reachable") else (
            "Utility model disabled." if not enabled else probe.get("error")
        ),
    }


def api_llm_util_test():
    settings = get_settings()
    enabled = str(settings.get("llm_util_enabled", "false")).lower() in ("true", "1", "yes")
    model = (settings.get("llm_util_model") or settings.get("lmstudio_model") or "").strip()
    url = settings.get("lmstudio_url")
    if not enabled:
        return {"ok": False, "error": "Utility model disabled in Settings.",
                "route": "utility", "url": url, "model": model, "duration_s": 0}
    t0 = time.time()
    try:
        with lmstudio_vram.vram_lock_for_text("utility"):
            prepare_vram_for_lmstudio(settings, "utility")
            lmstudio_vram.ensure_loaded(settings, "utility")
            reply = _lmstudio_chat(
                [{"role": "user", "content": "Reply only with: UTIL_OK"}],
                settings, max_tokens=96, temp=0.1, stop=None, role="utility")
        dur = round(time.time() - t0, 2)
        return {"ok": True, "reply": reply, "duration_s": dur,
                "route": "utility", "url": url, "model": model}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "duration_s": round(time.time() - t0, 2),
                "route": "utility", "url": url, "model": model}


def api_lmstudio_vram_status():
    """Etat actuel des modeles AmiorAI dans LM Studio (charges ou non), pour affichage dans
    Reglages -> Gestion VRAM LM Studio. N'effectue aucune action, lecture seule."""
    settings = get_settings()
    appl = lmstudio_vram.applicability(settings)
    conv_is_lmstudio = appl["conversational_applicable"]
    util_on_lmstudio = appl["utility_applicable"]

    result = {
        "applicable": appl["applicable"],
        "conversational_applicable": conv_is_lmstudio,
        "utility_applicable": util_on_lmstudio,
        "conversational_model": settings.get("lmstudio_model") if conv_is_lmstudio else "",
        "utility_model": (settings.get("llm_util_model") or settings.get("lmstudio_model")) if util_on_lmstudio else "",
        "conversational_loaded": False,
        "utility_loaded": False,
        "reachable": False,
        "error": None,
    }
    if not result["applicable"]:
        return result
    try:
        models = lmstudio_vram.list_native_models(settings)
        result["reachable"] = True
    except RuntimeError as e:
        result["error"] = str(e)
        return result

    if conv_is_lmstudio:
        result["conversational_loaded"] = bool(
            lmstudio_vram._find_loaded_instances(models, settings.get("lmstudio_model") or ""))
    if util_on_lmstudio:
        result["utility_loaded"] = bool(
            lmstudio_vram._find_loaded_instances(
                models, settings.get("llm_util_model") or settings.get("lmstudio_model") or ""))
    return result


def api_lmstudio_vram_unload_now():
    """Bouton 'Decharger maintenant' : decharge immediatement les modeles AmiorAI de LM
    Studio, independamment du reglage lmstudio_vram_offload_enabled (action manuelle
    explicite), et renvoie precisement ce qui a ete libere."""
    settings = get_settings()
    try:
        unloaded = lmstudio_vram.unload_now(settings)
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "unloaded": []}
    return {"ok": True, "unloaded": unloaded,
            "message": (f"{len(unloaded)} model(s) released: " + ", ".join(unloaded))
                       if unloaded else "No AmiorAI model loaded in LM Studio."}


def api_runtime_status():
    """Live textual lifecycle for LM Studio and ComfyUI used by Diagnostic."""
    settings = get_settings()
    llm_activity = llm_status()
    lifecycle = lmstudio_vram.lifecycle_status()
    vram = api_lmstudio_vram_status()
    comfy_live = comfy_generation_status(settings)
    try:
        comfy_base = comfy_status(settings)
    except Exception as exc:  # noqa: BLE001
        comfy_base = {"reachable": False, "error": str(exc)}
    return {
        "timestamp": time.time(),
        "lmstudio": {**vram, "activity": llm_activity, "lifecycle": lifecycle},
        "comfyui": {**comfy_base, "generation": comfy_live},
    }


# --------------------------------------------------------------------------- #
#  Health check
# --------------------------------------------------------------------------- #
ERRORS = []  # journal d'erreurs recent (ring buffer, affiche dans l'onglet Systeme)


def log_error(msg):
    ERRORS.append({"t": time.time(), "msg": str(msg)[:500]})
    del ERRORS[:-50]
    log.error(str(msg))


def api_health():
    s = get_settings()
    probe = llm_backends.probe_lmstudio(s)
    llm = {
        "backend": "lmstudio",
        "reachable": bool(probe.get("reachable")),
        "models": probe.get("models", []),
        "active_model": probe.get("active_model"),
        "error": probe.get("error"),
    }
    llm["status"] = "ready" if llm["reachable"] else "offline"
    llm["ok"] = llm["reachable"]

    try:
        comfy = comfy_status(s)
    except Exception as e:  # noqa: BLE001
        comfy = {"reachable": False, "error": str(e)}
    comfy["ok"] = bool(comfy.get("reachable"))
    comfy["external"] = True
    comfy["status"] = "ready" if comfy["ok"] else "offline"
    # VRAM via ComfyUI /system_stats si dispo
    try:
        comfy["vram"] = _comfy_vram(s)
    except Exception:
        comfy["vram"] = None

    wfs = {}
    img_tokens = {
        "i2i_workflow": ["%IMAGE%"],
        "duo_workflow": ["%IMAGE1%", "%IMAGE2%"],
        "trio_workflow": ["%IMAGE1%", "%IMAGE2%", "%IMAGE3%"],
        "group_workflow": ["%IMAGE1%", "%IMAGE2%", "%IMAGE3%", "%IMAGE4%"],
    }
    for key in ("t2i_workflow", "i2i_workflow", "duo_workflow", "trio_workflow", "group_workflow"):
        fname = s.get(key, "")
        fp = os.path.join(WF_DIR, fname)
        info = {"file": fname, "exists": os.path.exists(fp)}
        if info["exists"]:
            try:
                txt = open(fp, encoding="utf-8").read()
                json.loads(txt)
                info["valid_json"] = True
                info["has_prompt_token"] = s.get("prompt_token", "%PROMPT%") in txt
                missing = [t for t in img_tokens.get(key, []) if t not in txt]
                if key in img_tokens:
                    info["image_tokens_ok"] = not missing
                    if missing:
                        info["missing_tokens"] = missing
            except Exception as e:  # noqa: BLE001
                info["valid_json"] = False
                info["error"] = str(e)
        info["ok"] = info["exists"] and info.get("valid_json", False) \
            and info.get("image_tokens_ok", True)
        info["status"] = "ready" if info["ok"] else ("error" if info["exists"] else "gray")
        wfs[key] = info

    # TTS (optionnel : seulement si active)
    tts = {"enabled": str(s.get("tts_enabled", "false")).lower() in ("true", "1", "yes")}
    if tts["enabled"]:
        try:
            tts.update(tts_status(s))
        except Exception as e:  # noqa: BLE001
            tts["reachable"] = False
            tts["error"] = str(e)
        tts["status"] = ("error" if tts.get("engine_mismatch") or tts.get("error")
                         else "ready" if tts.get("model_status") == "ready"
                         else "loading" if tts.get("model_status") == "loading"
                         else "offline")
    else:
        tts["status"] = "gray"

    # Whisper (dictee, optionnel : seulement si active). Charge dans CE process (comme le LLM),
    # donc "ready" seulement une fois qu'une 1ere transcription a charge le modele en memoire.
    whisper = {"enabled": str(s.get("whisper_enabled", "false")).lower() in ("true", "1", "yes")}
    if whisper["enabled"]:
        try:
            whisper.update(whisper_status())
        except Exception as e:  # noqa: BLE001
            whisper["loaded"] = False
            whisper["error"] = str(e)
        whisper["status"] = "ready" if whisper.get("loaded") else "offline"
    else:
        whisper["status"] = "gray"

    last_err = ERRORS[-1] if ERRORS else None
    return {"llm": llm, "comfy": comfy, "tts": tts, "whisper": whisper, "workflows": wfs,
            "last_error": last_err, "errors": list(reversed(ERRORS[-15:]))}


# --------------------------------------------------------------------------- #
#  Persona (le joueur) + upload d'image + scene de groupe
# --------------------------------------------------------------------------- #
def get_persona_block(settings):
    name = (settings.get("persona_name") or "").strip()
    desc = (settings.get("persona_description") or "").strip()
    if not name and not desc:
        return ""
    block = "Informations sur l'utilisateur (le joueur) avec qui tu interagis :"
    if name:
        block += f" Il s'appelle {name}."
    if desc:
        block += f" {desc}"
    return block + "\n\n"


def api_upload_image(data_url, prefix="upload"):
    """Decode an image data URL into the persistent image folder."""
    header, raw = _decode_data_url(data_url, "image", 32 * 1024 * 1024)
    if "jpeg" in header or "jpg" in header:
        ext = "jpg"
        valid_magic = raw[:2] == b"\xff\xd8"
    elif "webp" in header:
        ext = "webp"
        valid_magic = raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    elif "gif" in header:
        ext = "gif"
        valid_magic = raw[:6] in (b"GIF87a", b"GIF89a")
    else:
        ext = "png"
        valid_magic = raw[:8] == b"\x89PNG\r\n\x1a\n"
    if not valid_magic:
        raise RuntimeError("The uploaded file does not match its declared image format.")
    safe_prefix = _safe_filename_token(prefix, "upload")
    name = f"{safe_prefix}_{new_id()}.{ext}"
    with open(os.path.join(IMG_DIR, name), "wb") as f:
        f.write(raw)
    return {"image": name}


def api_upload_voice_sample(character_id, data_url):
    """Decode un echantillon audio (data:URL base64) et l'enregistre comme voix de reference
    du personnage, dans data/voices/. 6-20s d'audio propre conviennent a Chatterbox et Qwen3-TTS."""
    if not character_id:
        raise RuntimeError("Personnage manquant.")
    header, raw = _decode_data_url(data_url, "voice sample", 64 * 1024 * 1024)
    # Detect the real container from its signature instead of trusting the browser MIME type.
    # This also gives M4A, FLAC, OGG and WebM their correct extension for local decoders.
    if len(raw) >= 12 and raw[:4] in (b"RIFF", b"RF64") and raw[8:12] == b"WAVE":
        ext = "wav"
    elif raw[:4] == b"fLaC":
        ext = "flac"
    elif raw[:4] == b"OggS":
        ext = "ogg"
    elif raw[:4] == b"\x1aE\xdf\xa3":
        ext = "webm"
    elif len(raw) >= 12 and raw[4:8] == b"ftyp":
        ext = "m4a"
    elif raw[:3] == b"ID3" or (len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0):
        ext = "mp3"
    else:
        declared = header.split(";", 1)[0].replace("data:", "")
        raise RuntimeError(
            f"Unsupported or invalid voice sample ({declared or 'unknown format'}). "
            "Use WAV, FLAC, MP3, M4A, OGG or WebM."
        )
    safe_character_id = _safe_filename_token(character_id, "character")
    name = f"voice_{safe_character_id}_{new_id()}.{ext}"
    path = os.path.join(VOICE_DIR, name)
    with open(path, "wb") as f:
        f.write(raw)
    with db() as c:
        c.execute("UPDATE characters SET voice_sample=? WHERE id=?", (name, character_id))
    return {"voice_sample": name}


def api_upload_dictation(data_url):
    """Decode un enregistrement audio (micro) en fichier temporaire pour transcription Whisper."""
    header, raw = _decode_data_url(data_url, "dictation audio", 64 * 1024 * 1024)
    ext = "webm"
    if "wav" in header:
        ext = "wav"
    elif "mp3" in header or "mpeg" in header:
        ext = "mp3"
    audio_dir = os.path.join(DATA_DIR, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    name = f"dictation_{new_id()}.{ext}"
    path = os.path.join(audio_dir, name)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def api_dictate(data_url, settings):
    """Transcrit un enregistrement micro en texte via Whisper local."""
    path = api_upload_dictation(data_url)
    try:
        result = whisper_transcribe(path, settings)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
    return result


def api_message_speak(message_id, settings):
    """Genere l'audio TTS d'un message (voix clonee du personnage qui l'a dit)."""
    with db() as c:
        msg = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not msg:
            raise RuntimeError("Message not found.")
        msg = dict(msg)
        char = None
        if msg.get("character_id"):
            row = c.execute("SELECT * FROM characters WHERE id=?", (msg["character_id"],)).fetchone()
            char = dict(row) if row else None
    if not char:
        raise RuntimeError("No character associated with this message.")
    voice = (char.get("voice_sample") or "").strip()
    if not voice:
        raise RuntimeError(f"{char.get('name','This character')} does not have a voice sample yet "
                           "(character profile -> Voice section).")
    voice_path = os.path.join(VOICE_DIR, voice)
    lang = settings.get("tts_language", "fr")
    speed = float(settings.get("tts_speed", 1.0) or 1.0)
    fname = tts_speak(
        msg["content"], voice_path, settings, language=lang, speed=speed,
        reference_text=(char.get("voice_transcript") or "").strip(),
    )
    with db() as c:
        c.execute("UPDATE messages SET audio=? WHERE id=?", (fname, message_id))
    return {"audio": fname}


def api_group_image(chat_id, message_id, with_persona=False, prompt=None, dry_run=False):
    """Generate a group scene through the globally selected image engine."""
    settings = get_settings()
    krea_active = (settings.get("image_family") or "").strip() == "krea2"
    with db() as c:
        msg = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not msg:
            raise RuntimeError("Message not found.")
    active = [m for m in _active_members(chat_id) if m.get("active", 1)]
    members = active if krea_active else [m for m in active if m.get("avatar")]
    if not members:
        requirement = "active character" if krea_active else "active character with an avatar"
        raise RuntimeError(f"No {requirement} in this conversation.")

    if krea_active:
        if prompt is None:
            prompt = build_krea_multi_subject_prompt(
                dict(msg)["content"], settings, members, include_persona=with_persona)
        if dry_run:
            return {"prompt": prompt, "refs": 0, "engine": "krea2"}
        img, used_seed = generate_t2i(prompt, settings, family="krea2")
    else:
        image_list, names = [], []
        if with_persona:
            pimg = (settings.get("persona_image") or "").strip()
            if pimg:
                image_list.append(pimg)
                names.append(_persona_label(settings))
        for member in members:
            image_list.append(member["avatar"])
            names.append(member.get("name") or "character")
        if len(image_list) > 4:
            image_list, names = image_list[:4], names[:4]
        if prompt is None:
            prompt = build_multiref_image_prompt(dict(msg)["content"], settings, names)
        if dry_run:
            return {"prompt": prompt, "refs": len(image_list), "engine": "flux2_klein"}
        workflow = (settings.get("duo_workflow", "duo.json") if len(image_list) <= 2
                    else settings.get("group_workflow", "group4.json"))
        img, used_seed = generate_group(prompt, image_list, settings, workflow=workflow)

    with db() as c:
        c.execute("UPDATE messages SET image=?, image_prompt=?, seed=? WHERE id=?",
                  (img, prompt, used_seed, message_id))
        c.execute("INSERT INTO gallery(id, character_id, image, prompt, seed, created_at) VALUES (?,?,?,?,?,?)",
                  (new_id(), members[0]["id"], img, prompt, used_seed, time.time()))
    return {"image": img, "prompt": prompt, "seed": used_seed, "with_persona": with_persona}


# --------------------------------------------------------------------------- #
#  Serveur HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "Companion/1.0"

    def log_message(self, *a):
        pass  # silence

    # ---- utilitys ----
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            # Le client (navigateur) a fermé la connexion avant la fin (page rechargee,
            # requete annulee, generation trop longue...). Rien a faire, on ignore.
            self._client_gone = True

    def _error(self, msg, code=400):
        if getattr(self, "_client_gone", False):
            return
        try:
            self._json({"error": str(msg)}, code)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            self._client_gone = True

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        ct = self.headers.get("Content-Type", "")
        if "application/x-www-form-urlencoded" in ct:
            import urllib.parse as _urlparse
            return dict(_urlparse.parse_qsl(raw.decode("utf-8", errors="replace")))
        if "multipart/form-data" in ct:
            # Parsing minimal multipart — retourne {"_multipart": True, "_raw": raw, "_ct": ct}
            return {"_multipart": True, "_raw": raw, "_ct": ct}
        return json.loads(raw.decode("utf-8"))

    def _extract_multipart_file(self, body: dict, field: str) -> bytes | None:
        """Extrait le contenu binaire d'un champ 'field' depuis un body multipart."""
        import email
        raw = body.get("_raw", b"")
        ct  = body.get("_ct", "")
        # email.message_from_bytes requiert Content-Type dans les headers
        msg = email.message_from_bytes(f"Content-Type: {ct}\r\n\r\n".encode() + raw)
        for part in msg.walk():
            disp = part.get("Content-Disposition", "")
            if f'name="{field}"' in disp or f"name={field}" in disp:
                return part.get_payload(decode=True)
        return None

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    # ---- GET ----
    def do_GET(self):
        # Vérification accès LAN si activé
        lan_mode = get_settings().get("lan_mode", "local")
        client_ip = (self.client_address or ("",))[0]
        if lan_mode == "lan" and not _lan_is_local(client_ip):
            cookie = self.headers.get("Cookie", "")
            parsed_path = urllib.parse.urlparse(self.path).path
            if parsed_path == "/lan_login":
                pass  # page login — accessible sans session
            elif not _lan_check_session(cookie):
                self.send_response(302)
                self.send_header("Location", "/lan_login")
                self.end_headers()
                return
            elif not _lan_route_allowed("GET", parsed_path):
                _lan_host_only_response(self)
                return
            else:
                # Client LAN authentifié sur "/" → rediriger vers /mobile
                if parsed_path in ("/", ""):
                    self.send_response(302)
                    self.send_header("Location", "/mobile")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/" or path == "/index.html":
                return self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            if path == "/app.js":
                return self._send_file(os.path.join(WEB_DIR, "app.js"), "application/javascript; charset=utf-8")
            if path == "/brand.js":
                return self._send_file(os.path.join(WEB_DIR, "brand.js"), "application/javascript; charset=utf-8")
            if path == "/icons.js":
                return self._send_file(os.path.join(WEB_DIR, "icons.js"), "application/javascript; charset=utf-8")
            if path == "/style.css":
                return self._send_file(os.path.join(WEB_DIR, "style.css"), "text/css; charset=utf-8")
            if path == "/icons.css":
                return self._send_file(os.path.join(WEB_DIR, "icons.css"), "text/css; charset=utf-8")
            if path == "/i18n.js":
                return self._send_file(os.path.join(WEB_DIR, "i18n.js"), "application/javascript; charset=utf-8")
            if path.startswith("/locales/") and path.endswith(".json"):
                lang = os.path.basename(path).replace(".json", "")
                locale_path = os.path.join(CODE_ROOT, "resources", "i18n", "locales", lang + ".json")
                if os.path.isfile(locale_path):
                    return self._send_file(locale_path, "application/json; charset=utf-8")
                return self._error("Locale not found: " + lang, 404)
            if path == "/api/settings/lang":
                s = get_settings()
                return self._json({"lang": s.get("ui_language", "en")})
            if path == "/api/i18n/export":
                master_path, _, _ = _get_i18n_paths()
                if not os.path.isfile(master_path):
                    return self._error(
                        f"Master file not found: {master_path}", 404
                    )
                with open(master_path, "rb") as f:
                    xlsx_bytes = f.read()
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition",
                                 'attachment; filename="translations_master.xlsx"')
                self.send_header("Content-Length", str(len(xlsx_bytes)))
                self.end_headers()
                self.wfile.write(xlsx_bytes)
                return
            if path == "/logo-icon-square.png":
                return self._send_file(os.path.join(WEB_DIR, path.lstrip("/")), "image/png")
            if path.startswith("/assets/icons/"):
                asset_name = os.path.basename(urllib.parse.unquote(path))
                if not asset_name.endswith(".png"):
                    return self._error("Type d'icône non autorisé.", 404)
                asset_path = os.path.join(WEB_DIR, "assets", "icons", asset_name)
                return self._send_file(asset_path, "image/png")
            if path.startswith("/img/"):
                raw_name = path[len("/img/"):]
                name = os.path.basename(urllib.parse.unquote(raw_name))
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                ct = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                      "webp": "image/webp", "gif": "image/gif"}.get(ext, "application/octet-stream")
                img_path, is_legacy = resolve_img(name)
                if not os.path.isfile(img_path):
                    logging.warning("[/img/] Image not found: %s (searched in %s and %s)",
                                    name, IMG_DIR, LEGACY_IMG_DIR)
                    return self._error("Image not found: " + name, 404)
                if is_legacy:
                    logging.warning("[/img/] Image servie depuis location legacy : %s", img_path)
                return self._send_file(img_path, ct)
            if path.startswith("/lora_preview/civitai/"):
                name = os.path.basename(path[len("/lora_preview/civitai/"):])
                ext  = name.rsplit(".", 1)[-1].lower()
                ct   = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "webp": "image/webp"}.get(ext, "image/jpeg")
                return self._send_file(os.path.join(CIVITAI_CACHE_DIR, name), ct)
            if path.startswith("/audio/"):
                name = os.path.basename(path[len("/audio/"):])
                ext = name.rsplit(".", 1)[-1].lower()
                ct = {"wav": "audio/wav", "mp3": "audio/mpeg", "webm": "audio/webm",
                      "ogg": "audio/ogg"}.get(ext, "application/octet-stream")
                return self._send_file(os.path.join(DATA_DIR, "audio", name), ct)

            if path == "/api/settings":
                return self._json(_get_safe_settings(is_local=_lan_is_local(client_ip)))
            if path == "/api/advanced_prompts":
                return self._json(api_advanced_prompts_get())
            if path == "/api/characters":
                return self._json(api_characters_list())
            if path == "/api/character":
                return self._json(api_character_get(qs.get("id", [""])[0]))
            if path == "/api/chats":
                return self._json(api_chats_list())
            if path == "/api/chat":
                return self._json(api_chat_messages(qs.get("id", [""])[0]))
            if path == "/api/gallery":
                cid    = qs.get("character_id", [None])[0]
                limit  = int(qs.get("limit",  [0])[0] or 0)
                offset = int(qs.get("offset", [0])[0] or 0)
                rows   = api_gallery(cid)
                if offset:
                    rows = rows[offset:]
                return self._json(rows[:limit] if limit else rows)
            if path == "/mobile":
                # Interface mobile LAN
                mobile_path = os.path.join(CODE_ROOT, "web", "mobile.html")
                if os.path.exists(mobile_path):
                    self._send_file(mobile_path, "text/html; charset=utf-8")
                else:
                    self._error("Mobile interface not found.", 404)
                return
            if path == "/api/client-context":
                is_local = _lan_is_local(client_ip)
                caps = list(_LAN_ALLOWED_POST | {r for r in _LAN_ALLOWED_GET if r.startswith("/api/")})
                return self._json({
                    "access_mode": "host" if is_local else "lan",
                    "ui_mode": "desktop" if is_local else "mobile",
                    "is_host": is_local,
                    "capabilities": sorted(caps) if not is_local else ["all"],
                })
            if path == "/lan_login":
                # Page de connexion LAN
                error_msg = ""
                body = _LAN_LOGIN_HTML.replace("{error}", "").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/lan/info":
                # Infos réseau local — accessible uniquement depuis le PC hôte
                if not _lan_is_local(client_ip):
                    return self._json({"ok": False,
                        "error": "This action must be performed from the host PC."})
                s = get_settings()
                mode = s.get("lan_mode", "local")
                local_ip = _lan_get_local_ip() if mode == "lan" else _lan_get_local_ip()
                return self._json({
                    "mode": mode,
                    "local_ip": local_ip,
                    "port": PORT,
                    "url": f"http://{local_ip}:{PORT}",
                    "code_set": bool(s.get("lan_access_code_hash")),
                    "active_sessions": _lan_count_sessions(),
                })
            if path == "/api/health":
                return self._json(api_health())
            if path == "/api/llm/status":
                return self._json(llm_status())
            if path == "/api/runtime/status":
                return self._json(api_runtime_status())
            if path == "/api/tts/status":
                return self._json(tts_status(get_settings()))
            if path == "/api/memory":
                return self._json(api_memory_list(qs.get("character_id", [""])[0]))
            if path == "/api/config/previews":
                return self._json(api_config_previews())
            if path == "/api/char_memory":
                cid = qs.get("character_id", [""])[0]
                return self._json(get_char_memory(cid))
            if path == "/api/char_mood":
                cid = qs.get("character_id", [""])[0]
                state = get_char_mood(cid)
                mood = state.get("mood", "neutral")
                return self._json({**state,
                    "mood_style": MOOD_STYLE.get(mood, ""),
                    "mood_image": MOOD_IMAGE.get(mood, ""),
                    "current_emotion": MOOD_TO_EMOTION.get(mood, "calm")})
            if path == "/api/char_emotions":
                cid = qs.get("character_id", [""])[0]
                return self._json(get_char_emotions(cid))
            if path == "/api/scenarios":
                return self._json(api_scenario_list())
            if path == "/api/journal":
                cid = qs.get("character_id", [None])[0]
                return self._json(api_journal_list(cid))
            if path == "/api/loras":
                return self._json(api_lora_list())
            if path == "/api/lora/library":
                family         = qs.get("family",         [None])[0]
                search         = qs.get("search",         [None])[0]
                favonly        = qs.get("favorites_only", ["false"])[0] == "true"
                preview_filter = qs.get("preview_filter", [None])[0]
                return self._json(api_lora_library(family=family, search=search,
                                                    favorites_only=favonly,
                                                    preview_filter=preview_filter))
            if path == "/api/lora/presets":
                context    = qs.get("context",    [None])[0]
                context_id = qs.get("context_id", [None])[0]
                family     = qs.get("family",     [None])[0]
                return self._json(api_lora_presets_list(context=context,
                                  context_id=context_id, family=family))
            if path == "/api/lora/workflow_compat":
                return self._json(api_lora_workflow_compat(qs.get("wf_name", [None])[0]))
            if path == "/api/lora/preview":
                return self._json(api_lora_preview_get(qs.get("lora_name", [None])[0] or ""))
            if path == "/api/lora/previews":
                return self._json(api_lora_previews_list())
            if path == "/api/chat/lora":
                return self._json(api_chat_lora_get(qs.get("chat_id", [None])[0] or ""))
            # ---- Civitai ----
            if path == "/api/civitai/token_status":
                return self._json(_civitai_token_status())
            if path == "/api/civitai/test":
                return self._json(api_civitai_token_test())
            if path == "/api/civitai/metadata":
                mfid = qs.get("model_file_id", [None])[0]
                if mfid:
                    return self._json(api_civitai_metadata_get(mfid))
                return self._json(api_civitai_metadata_list())
            if path == "/api/civitai/sync_status":
                return self._json(api_civitai_sync_status())
            if path == "/api/character/export":
                data = api_export_character(qs.get("id", [""])[0])
                body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="personnage_%s.json"' % qs.get("id", [""])[0])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            # ---- Bibliothèque de modèles ----
            if path == "/api/models/folders":
                return self._json(api_model_folders_list())
            if path == "/api/models/files":
                kind = qs.get("kind", [None])[0]
                family = qs.get("family", [None])[0]
                include_missing = qs.get("include_missing", ["false"])[0] == "true"
                only_enabled = qs.get("only_enabled", ["true"])[0] != "false"
                return self._json(api_model_files_list(kind=kind, family=family,
                                  only_enabled_folders=only_enabled, include_missing=include_missing))
            if path == "/api/models/summary":
                return self._json(api_model_catalog_summary())

            # ---- Studio Image ----
            if path == "/api/image/families":
                return self._json(api_image_families())
            if path == "/api/image/workflows":
                family = qs.get("family", [None])[0]
                return self._json(api_image_workflows(family))
            if path == "/api/image/compatibility":
                family = qs.get("family", [get_settings().get("image_family", "flux2_klein")])[0]
                return self._json(api_image_compatibility(family))
            if path == "/api/loras/duplicates":
                return self._json(api_loras_duplicates_list())
            if path == "/api/loras/duplicates/status":
                return self._json(api_loras_duplicates_status())
            if path == "/api/models/enriched":
                kind   = qs.get("kind",   [None])[0]
                family = qs.get("family", [None])[0]
                return self._json(api_models_enriched(kind=kind, family=family))
            if path == "/api/models/wishlist":
                return self._json(api_model_wishlist_list())
            if path == "/api/diagnostic":
                try:
                    family = qs.get("family", [None])[0]
                    report = diag_module.run_all(
                        get_settings(), DB_PATH, DATA_DIR, WF_DIR, IMG_DIR, image_family=family)
                except Exception as e:
                    report = {"error": str(e), "sections": [], "summary": {"ok": 0, "warning": 0, "error": 1}}
                return self._json(report)
            if path == "/api/image/unet_loader_info":
                # Interroge ComfyUI pour obtenir les valeurs weight_dtype autorisées par UNETLoader
                info = comfy_unet_loader_info(get_settings())
                return self._json(info or {"allowed": ["default", "fp8_e4m3fn", "fp8_e5m2", "fp16", "bf16"], "default": "default"})
            if path == "/api/comfy/loras":
                # Liste des LoRA connues de ComfyUI (noms exacts acceptés par LoraLoader)
                names = comfy_list_loras(get_settings())
                return self._json({"loras": names, "count": len(names)})
            if path == "/api/lora/slot_info":
                family = qs.get("family", [None])[0]
                info = model_manifests.get_lora_slot_info(family) if family else {
                    fid: model_manifests.get_lora_slot_info(fid)
                    for fid in model_manifests.LORA_SLOT_MAP
                }
                return self._json(info or {})

            # ---- Catalogue / backends LLM ----
            if path == "/api/llm/backends":
                return self._json(api_llm_backends_list())
            if path == "/api/llm/backend_status":
                bid = qs.get("backend", ["internal"])[0]
                return self._json(api_llm_backend_status(bid))
            if path == "/api/llm/catalog":
                return self._json(api_llm_catalog())
            if path == "/api/llm/util_status":
                return self._json(api_llm_util_status())
            if path == "/api/llm/lmstudio_vram_status":
                return self._json(api_lmstudio_vram_status())

            self.send_response(404)
            self.end_headers()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self._client_gone = True
        except Exception as e:  # noqa: BLE001
            log_error(e)
            self._error(repr(e), 500)

    # ---- POST ----
    def do_POST(self):
        # Vérification accès LAN si activé
        lan_mode = get_settings().get("lan_mode", "local")
        client_ip = (self.client_address or ("",))[0]
        if lan_mode == "lan" and not _lan_is_local(client_ip):
            cookie = self.headers.get("Cookie", "")
            parsed_path = urllib.parse.urlparse(self.path).path
            if parsed_path == "/lan_login":
                pass  # page login POST — autorisée
            elif not _lan_check_session(cookie):
                self._error("Unauthorized — unauthenticated LAN access.", 401)
                return
            elif not _lan_route_allowed("POST", parsed_path):
                _lan_host_only_response(self)
                return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_body()

            # ── Import xlsx multipart (traité avant le parsing JSON normal) ──
            if path == "/api/i18n/import-file":
                if not body.get("_multipart"):
                    return self._json({
                        "ok": False,
                        "error_code": "NOT_MULTIPART",
                        "message": "Expected multipart/form-data request."
                    })
                xlsx_bytes = self._extract_multipart_file(body, "file")
                if not xlsx_bytes:
                    return self._json({
                        "ok": False,
                        "error_code": "NO_FILE_FIELD",
                        "message": "Missing 'file' field in request.",
                    })
                # Stockage temporaire + validation + remplacement du maître
                import tempfile, shutil
                master_path, locales_dir, _ = _get_i18n_paths()
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                    tmp.write(xlsx_bytes)
                    tmp_path = tmp.name
                try:
                    # Validation du fichier importé
                    result = _i18n_call_generate(master_path=tmp_path, dry_run=True)
                    if not result.get("ok"):
                        return self._json(result)
                    # Sauvegarde de l'ancien maître
                    import datetime as _dt
                    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                    bak = master_path + f".bak_{ts}"
                    if os.path.isfile(master_path):
                        shutil.copy2(master_path, bak)
                    # Remplacement + génération des JSON
                    shutil.copy2(tmp_path, master_path)
                    result = _i18n_call_generate(master_path=master_path, dry_run=False)
                    if result.get("ok"):
                        _i18n_reload_locales()
                    return self._json(result)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

            if path == "/api/settings":
                if not _lan_is_local(client_ip):
                    # Clients LAN : rejeter les clés admin-only
                    blocked = [k for k in body if k in _SETTINGS_ADMIN_ONLY]
                    if blocked:
                        return self._json({
                            "ok": False,
                            "error": "This action must be performed from the host PC.",
                            "blocked_keys": blocked
                        })
                save_settings(body)
                return self._json({"ok": True})

            # ── Routes i18n ──────────────────────────────────────────────────
            if path == "/api/settings/lang":
                lang = body.get("lang", "en")
                if lang not in ("fr", "en", "es", "de"):
                    return self._json({"ok": False, "error_code": "UNSUPPORTED_LANG",
                                       "message": f"Unsupported language: {lang}"})
                save_settings({"ui_language": lang})
                _i18n_reload_locales()  # vide le cache i18n_backend
                return self._json({"ok": True, "lang": lang})

            if path == "/api/i18n/reload":
                _i18n_reload_locales()
                return self._json({"ok": True, "message": "i18n cache cleared — translations reloaded."})

            if path == "/api/i18n/stats":
                return self._json(_i18n_stats())

            if path in ("/api/i18n/generate", "/api/i18n/analyze"):
                dry = bool(body.get("dry_run", False)) or path == "/api/i18n/analyze"
                result = _i18n_call_generate(dry_run=dry)
                if result.get("ok") and not dry:
                    _i18n_reload_locales()  # applique immédiatement
                return self._json(result)

            if path == "/api/i18n/import":
                # Alias de sécurité : déclenche une analyse dry-run du fichier maître existant.
                # Pour importer un nouveau fichier, utiliser POST /api/i18n/import-file (multipart).
                result = _i18n_call_generate(dry_run=True)
                return self._json(result)

            if path == "/api/i18n/restore-last-backup":
                result = _i18n_restore_backup()
                if result.get("ok"):
                    _i18n_reload_locales()
                return self._json(result)

            # Alias de compatibilité ancienne route
            if path == "/api/i18n/restore_backup":
                result = _i18n_restore_backup()
                if result.get("ok"):
                    _i18n_reload_locales()
                return self._json(result)
            # ────────────────────────────────────────────────────────────────

            if path == "/api/advanced_prompts/save":
                return self._json(api_advanced_prompts_save(
                    body.get("key", ""), body.get("value", "")))
            if path == "/api/advanced_prompts/reset":
                return self._json(api_advanced_prompts_reset(body.get("key")))
            if path == "/api/advanced_prompts/restore":
                return self._json(api_advanced_prompts_restore(body.get("key", "")))

            if path == "/api/character/generate":
                data = generate_character(body.get("brief", ""), get_settings(), body.get("attrs"))
                return self._json(data)

            if path == "/api/character/save":
                return self._json(api_character_save(body))

            if path == "/api/character/delete":
                api_character_delete(body.get("id"))
                return self._json({"ok": True})

            if path == "/api/character/avatar":
                # genere/reroll un avatar ; options keep_seed / variant / prompt corrige / dry_run
                cid = body.get("id")
                if not cid:
                    settings = get_settings()
                    if body.get("dry_run"):
                        return self._json({"prompt": body.get("image_prompt", "")})
                    img, seed = generate_t2i(body.get("prompt") or body.get("image_prompt", ""), settings)
                    return self._json({"image": img, "seed": seed})
                res = api_avatar_generate(cid, keep_seed=bool(body.get("keep_seed")),
                                          variant=body.get("variant", ""),
                                          prompt=body.get("prompt"), dry_run=bool(body.get("dry_run")),
                                          canonical_profile=bool(body.get("canonical_profile")))
                if not body.get("dry_run") and body.get("set_as_main"):
                    api_set_main_avatar(cid, res["image"])
                return self._json(res)

            if path == "/api/character/set_avatar":
                return self._json(api_set_main_avatar(body.get("id"), body.get("image")))

            if path == "/api/character/import":
                return self._json(api_import_character(body))

            if path == "/api/memory/add":
                return self._json(api_memory_add(body.get("character_id"), body.get("kind", "short"),
                                                 body.get("content", "")))
            if path == "/api/memory/delete":
                api_memory_delete(body.get("id"))
                return self._json({"ok": True})
            if path == "/api/memory/summarize":
                return self._json(api_memory_summarize(body.get("character_id"), body.get("chat_id")))

            if path == "/api/chat/create":
                cid = api_chat_create(body.get("members", []), body.get("title"))
                return self._json({"id": cid})

            if path == "/api/chat/delete":
                api_chat_delete(body.get("id"))
                return self._json({"ok": True})

            if path == "/api/chat/member_active":
                api_set_member_active(body.get("chat_id"), body.get("character_id"),
                                      bool(body.get("active")))
                return self._json({"ok": True})

            if path == "/api/message/send":
                return self._json(api_send_message(
                    body.get("chat_id"), body.get("content", ""), body.get("responder_id")))

            if path == "/api/message/react":
                return self._json(api_react(body.get("chat_id"), body.get("responder_id")))

            if path == "/api/message/image":
                return self._json(api_generate_in_chat(
                    body.get("chat_id"), body.get("message_id"),
                    with_persona=bool(body.get("with_persona")),
                    prompt=body.get("prompt"), dry_run=bool(body.get("dry_run"))))

            if path == "/api/message/group_image":
                return self._json(api_group_image(
                    body.get("chat_id"), body.get("message_id"),
                    with_persona=bool(body.get("with_persona")),
                    prompt=body.get("prompt"), dry_run=bool(body.get("dry_run"))))

            if path == "/api/upload":
                return self._json(api_upload_image(body.get("data_url", ""),
                                                   body.get("prefix", "upload")))

            if path == "/api/message/regenerate":
                return self._json(api_regenerate_image(body.get("message_id"),
                                                       keep_seed=bool(body.get("keep_seed")),
                                                       prompt=body.get("prompt")))

            if path == "/api/char_mood/set":
                cid = body.pop("character_id", None)
                if not cid:
                    raise RuntimeError("character_id manquant.")
                state = get_char_mood(cid)
                allowed = set(MOOD_DEFAULTS.keys())
                for k, v in body.items():
                    if k in allowed:
                        state[k] = _clamp(v)
                new_mood = _calc_mood(state)
                with db() as c:
                    c.execute("INSERT OR REPLACE INTO char_mood "
                              "(character_id, affection, trust, energy, curiosity, stress, "
                              " mood, mood_since, last_msg_id, updated_at) "
                              "VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (cid, state["affection"], state["trust"], state["energy"],
                               state["curiosity"], state["stress"],
                               new_mood, 0, state.get("last_msg_id",""), time.time()))
                return self._json(get_char_mood(cid))

            if path == "/api/char_memory/save":
                cid = body.pop("character_id", None)
                if not cid:
                    raise RuntimeError("character_id manquant.")
                save_char_memory(cid, **body)
                return self._json(get_char_memory(cid))

            if path == "/api/char_emotion/generate":
                return self._json(api_generate_emotion_portrait(
                    body.get("character_id"), body.get("emotion"),
                    dry_run=bool(body.get("dry_run")), prompt=body.get("prompt")))

            if path == "/api/scenario/save":
                return self._json(api_scenario_save(body))
            if path == "/api/scenario/delete":
                return self._json(api_scenario_delete(body.get("id")))
            if path == "/api/scenario/generate":
                return self._json(api_scenario_generate(body, get_settings()))
            if path == "/api/scenario/apply":
                return self._json(api_scenario_apply(body.get("chat_id"), body.get("scenario_id")))
            if path == "/api/scenario/clear":
                with db() as c:
                    c.execute("UPDATE chats SET scenario_id=NULL WHERE id=?", (body.get("chat_id"),))
                return self._json({"ok": True})

            if path == "/api/journal/add":
                return self._json(api_journal_add(
                    body.get("character_id"), body.get("kind", "moment"),
                    body.get("title", ""), body.get("content", ""),
                    image=body.get("image", ""), date=body.get("date"),
                    pinned=body.get("pinned", 0)))
            if path == "/api/journal/delete":
                return self._json(api_journal_delete(body.get("id")))
            if path == "/api/journal/pin":
                return self._json(api_journal_pin(body.get("id"), body.get("pinned")))
            if path == "/api/journal/generate":
                return self._json(api_journal_generate(body.get("character_id"), get_settings()))

            if path == "/api/lora/save":
                return self._json(api_lora_save(body))
            if path == "/api/lora/delete":
                return self._json(api_lora_delete(body.get("id")))
            if path == "/api/lora/toggle":
                return self._json(api_lora_toggle(body.get("id"), bool(body.get("always_on"))))
            if path == "/api/lora/favorite":
                return self._json(api_lora_favorite(body.get("id"), bool(body.get("favorite"))))
            if path == "/api/lora/preset/save":
                return self._json(api_lora_preset_save(body))
            if path == "/api/lora/preset/delete":
                return self._json(api_lora_preset_delete(body.get("id")))
            if path == "/api/lora/preset/apply":
                return self._json(api_lora_preset_apply(body.get("id")))
            if path == "/api/lora/preview/generate":
                return self._json(api_lora_preview_generate(
                    lora_name=body.get("lora_name", ""),
                    family=body.get("family"),
                    prompt=body.get("prompt"),
                    negative=body.get("negative"),
                    seed=body.get("seed"),
                ))
            if path == "/api/lora/preview/assign":
                return self._json(api_lora_preview_assign(
                    lora_name=body.get("lora_name", ""),
                    family=body.get("family"),
                    source=body.get("source", "selected_gallery"),
                    image=body.get("image"),
                    image_b64=body.get("image_b64"),
                ))
            if path == "/api/lora/preview/delete":
                return self._json(api_lora_preview_delete(body.get("lora_name", "")))
            # --- Sélection LoRA par conversation ---
            if path == "/api/chat/lora/set":
                return self._json(api_chat_lora_set(
                    body.get("chat_id", ""), body.get("primary"),
                    body.get("secondary"), bool(body.get("apply_once"))))
            if path == "/api/chat/lora/clear":
                return self._json(api_chat_lora_clear(body.get("chat_id", "")))
            # ---- Civitai ----
            if path == "/lan_login":
                # Validation code LAN — body déjà lu par _read_body() plus haut
                code_input = (body.get("code") or "").strip()
                s_cfg = get_settings()
                stored_hash = s_cfg.get("lan_access_code_hash", "").strip()

                def _send_login_page(err_msg):
                    err_html = f'<p class="err">{err_msg}</p>' if err_msg else ""
                    resp = _LAN_LOGIN_HTML.replace("{error}", err_html).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)

                # Rate limiting (jamais pour localhost)
                if not _lan_is_local(client_ip) and _lan_is_rate_limited(client_ip):
                    _send_login_page("Too many attempts. Try again in a few minutes.")
                    return

                if not stored_hash:
                    _send_login_page("No code configured. Generate one from the host PC.")
                elif _lan_verify_code(code_input, stored_hash):
                    _lan_clear_fail(client_ip)
                    token = _lan_new_session()
                    self.send_response(302)
                    self.send_header("Set-Cookie", _lan_session_cookie(token))
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    _lan_record_fail(client_ip)
                    _send_login_page("Unable to log in. Check the access code.")
                return
            if path == "/api/lan/code/generate":
                # Générer un code LAN 8 chiffres — stocké hashé, jamais en clair
                if not _lan_is_local(client_ip):
                    return self._json({"ok": False,
                        "error": "This action must be performed from the host PC."})
                new_code = str(_secrets.randbelow(10**8)).zfill(8)
                code_hash = _lan_hash_code(new_code)
                save_settings({"lan_access_code_hash": code_hash,
                               "lan_access_code": ""})   # effacer l'ancien clair
                _lan_revoke_all_sessions()               # invalider les sessions existantes
                return self._json({"ok": True, "code": new_code,
                                   "note": "Write this code down — it will not be shown again."})
            if path == "/api/lan/sessions/revoke":
                if not _lan_is_local(client_ip):
                    return self._json({"ok": False,
                        "error": "This action must be performed from the host PC."})
                _lan_revoke_all_sessions()
                return self._json({"ok": True, "message": "All LAN sessions have been revoked."})
            if path == "/api/lan/logout":
                # Déconnexion LAN : invalider la session côté serveur + expirer le cookie
                cookie = self.headers.get("Cookie", "")
                if cookie:
                    for part in cookie.split(";"):
                        part = part.strip()
                        if part.startswith(_LAN_COOKIE_NAME + "="):
                            token = part[len(_LAN_COOKIE_NAME)+1:].split()[0]
                            _lan_sessions.pop(token, None)
                expired_cookie = f"{_LAN_COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"
                data = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", expired_cookie)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/civitai/token/save":
                return self._json(api_civitai_token_save(body.get("token", "")))
            if path == "/api/civitai/token/delete":
                return self._json(api_civitai_token_delete())
            if path == "/api/civitai/enrich":
                return self._json(api_civitai_enrich_one(body.get("model_file_id", "")))
            if path == "/api/civitai/sync":
                return self._json(api_civitai_sync(body.get("mode", "missing")))
            if path == "/api/civitai/sync/cancel":
                return self._json(api_civitai_sync_cancel())
            # v21 — association manuelle + identification
            if path == "/api/civitai/fetch_by_url":
                return self._json(api_civitai_fetch_by_url(body.get("url", "")))
            if path == "/api/civitai/fetch_version":
                return self._json(api_civitai_fetch_version(int(body.get("version_id", 0))))
            if path == "/api/civitai/associate":
                return self._json(api_civitai_associate(
                    body.get("model_file_id", ""),
                    body.get("civitai_data", {}),
                ))
            if path == "/api/lora/set_identification":
                return self._json(api_lora_set_identification(
                    body.get("model_file_id", ""),
                    body.get("manual_file_type"),
                    body.get("manual_family"),
                    bool(body.get("reset")),
                ))

            # ---- Bibliothèque de modèles ----
            if path == "/api/models/folders/add":
                return self._json(api_model_folder_add(body.get("path"), body.get("kind_hint")))
            if path == "/api/models/folders/remove":
                return self._json(api_model_folder_remove(body.get("id")))
            if path == "/api/models/folders/toggle":
                return self._json(api_model_folder_toggle(body.get("id"), bool(body.get("enabled"))))
            if path == "/api/models/folders/rescan":
                return self._json(api_model_folder_rescan(body.get("id")))
            if path == "/api/lora/civitai/dissociate":
                return self._json(api_civitai_dissociate(body.get("model_file_id", "")))
            if path == "/api/loras/analyze_duplicates":
                return self._json(api_loras_analyze_duplicates())
            if path == "/api/models/wishlist/add":
                return self._json(api_model_wishlist_add(
                    body.get("url", ""), body.get("notes", "")))
            if path == "/api/models/wishlist/remove":
                return self._json(api_model_wishlist_remove(body.get("id", "")))
            if path == "/api/models/wishlist/check":
                return self._json(api_model_wishlist_check(body.get("id", "")))
            if path == "/api/models/files/identify":
                return self._json(api_model_file_set_identification(
                    body.get("id", ""),
                    body.get("manual_kind"),
                    body.get("manual_family"),
                    bool(body.get("reset")),
                ))
            if path == "/api/models/files/delete":
                return self._json(api_model_file_delete(body.get("id", "")))
            if path == "/api/models/files/delete/batch":
                return self._json(api_model_file_delete_batch(body.get("ids", [])))
            if path == "/api/models/files/identify/batch":
                ids         = body.get("ids") or []
                manual_kind = body.get("manual_kind") or None
                manual_family = body.get("manual_family") or None
                reset       = bool(body.get("reset"))
                if not ids:
                    return self._json({"ok": False, "error": "No file selected."})
                updated, errors = 0, []
                for fid in ids:
                    try:
                        api_model_file_set_identification(fid, manual_kind, manual_family, reset)
                        updated += 1
                    except Exception as e:
                        errors.append({"id": fid, "error": str(e)})
                return self._json({"ok": True, "updated": updated, "errors": errors})

            # ---- Studio Image ----
            if path == "/api/image/set_family":
                family = (body.get("family") or "flux2_klein").strip()
                if family not in ("flux2_klein", "krea2"):
                    return self._json({"ok": False, "error": "Unsupported image engine."}, status=400)
                save_settings({"image_family": family})
                return self._json({"ok": True, "image_family": family})
            if path == "/api/image/set_workflow":
                # cle de reglage du workflow actif pour la famille (ex: t2i_workflow pour flux2_klein,
                # ou une cle generique 'active_workflow' pour les autres familles)
                save_settings({body.get("setting", "active_workflow"): body.get("file", "")})
                return self._json({"ok": True})
            if path == "/api/image/set_component":
                return self._json(api_image_set_component(
                    body.get("family"), body.get("component"), body.get("value")))
            if path == "/api/image/set_show_incompatible":
                save_settings({"image_show_incompatible": "true" if body.get("show") else "false"})
                return self._json({"ok": True})
            if path == "/api/image/generate":
                return self._json(api_image_generate(
                    body.get("family"), body.get("workflow"), body.get("prompt", ""),
                    negative=body.get("negative"), seed=body.get("seed"),
                    images=body.get("images")))

            # ---- LLM : actions (charger / décharger / tester) ----
            if path == "/api/llm/load":
                settings = get_settings()
                try:
                    with lmstudio_vram.vram_lock_for_text("conversation"):
                        prepare_vram_for_lmstudio(settings, "conversation")
                        lmstudio_vram.ensure_loaded(settings, "conversation")
                    return self._json({"ok": True, "status": api_llm_backend_status("lmstudio")})
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(e)})
            if path == "/api/llm/unload":
                result = api_lmstudio_vram_unload_now()
                return self._json(result)
            if path == "/api/llm/validate_path":
                return self._json(api_llm_validate_path(body.get("path")))
            if path == "/api/llm/set_backend":
                save_settings({"llm_backend": "lmstudio"})
                return self._json({"ok": True, "backend": "lmstudio"})
            if path == "/api/llm/test":
                # Test simple : un message court, mesure de la duree, pas de modification d'etat
                settings = get_settings()
                t0 = time.time()
                try:
                    reply = llm_chat(
                        [{"role": "user", "content": "Reply only with the word: ok"}],
                        settings, max_tokens=10, temperature=0.1)
                    dur = round(time.time() - t0, 2)
                    return self._json({"ok": True, "reply": reply, "duration_s": dur})
                except Exception as e:  # noqa: BLE001
                    dur = round(time.time() - t0, 2)
                    return self._json({"ok": False, "error": str(e), "duration_s": dur})
            if path == "/api/llm/util_test":
                return self._json(api_llm_util_test())
            if path == "/api/llm/lmstudio_vram_unload_now":
                return self._json(api_lmstudio_vram_unload_now())

            if path == "/api/chat/scene_mode":
                # Bascule le mode scène (is_group sans responder auto, personnages posés)
                with db() as c:
                    c.execute("UPDATE chats SET is_group=? WHERE id=?",
                              (1 if body.get("active") else 0, body.get("chat_id")))
                return self._json({"ok": True})

            if path == "/api/chat/add_member":
                return self._json(api_chat_add_member(body.get("chat_id"), body.get("character_id")))

            if path == "/api/chat/remove_member":
                cid = body.get("chat_id"); mid = body.get("character_id")
                if not cid or not mid:
                    raise RuntimeError("chat_id ou character_id manquant.")
                with db() as c:
                    c.execute("DELETE FROM chat_members WHERE chat_id=? AND character_id=?", (cid, mid))
                    n = c.execute("SELECT COUNT(*) AS n FROM chat_members WHERE chat_id=?", (cid,)).fetchone()["n"]
                    if n <= 1:
                        c.execute("UPDATE chats SET is_group=0 WHERE id=?", (cid,))
                return self._json({"ok": True})

            if path == "/api/message/regenerate_text":
                return self._json(api_regenerate_text(body.get("message_id")))

            if path == "/api/message/continue":
                return self._json(api_continue_message(body.get("message_id")))

            if path == "/api/message/background":
                return self._json(api_generate_background(
                    body.get("chat_id"), body.get("message_id"),
                    prompt=body.get("prompt"), dry_run=bool(body.get("dry_run"))))

            if path == "/api/config/preview":
                return self._json(api_config_preview(body.get("field"), body.get("value"),
                                                     gender=body.get("gender", ""),
                                                     regen=bool(body.get("regen"))))

            if path == "/api/comfy/free":
                s = get_settings()
                vram_before = _comfy_vram(s)
                try:
                    comfy_free(s)
                except RuntimeError as e:
                    return self._json({"ok": False, "message": str(e),
                                       "vram_before": vram_before, "vram_after": None,
                                       "freed_mb": None})
                vram_after = _comfy_vram(s)
                freed_mb = None
                if vram_before and vram_after:
                    freed_mb = (vram_after.get("free_mb") or 0) - (vram_before.get("free_mb") or 0)
                return self._json({"ok": True, "message": "ComfyUI VRAM released.",
                                   "vram_before": vram_before, "vram_after": vram_after,
                                   "freed_mb": freed_mb})
            if path == "/api/llm/free":
                free_llm()
                return self._json({"ok": True, "msg": "LLM decharge."})

            if path == "/api/tts/start":
                return self._json(tts_start(get_settings()))
            if path == "/api/tts/stop":
                tts_stop()
                return self._json({"ok": True, "msg": "Serveur TTS arrete."})
            if path == "/api/tts/restart":
                return self._json(tts_restart(get_settings()))
            if path == "/api/tts/kill":
                return self._json(tts_kill(get_settings()))

            if path == "/api/voice/upload":
                return self._json(api_upload_voice_sample(body.get("character_id"), body.get("data_url", "")))

            if path == "/api/message/speak":
                return self._json(api_message_speak(body.get("message_id"), get_settings()))

            if path == "/api/dictate":
                return self._json(api_dictate(body.get("data_url", ""), get_settings()))

            self.send_response(404)
            self.end_headers()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self._client_gone = True
        except urllib.error.URLError as e:
            log_error(e)
            self._error(f"Connection failed (LM Studio or ComfyUI). Check Settings. Detail: {e}", 502)
        except Exception as e:  # noqa: BLE001
            log_error(e)
            self._error(repr(e), 500)


def start_server():
    """Start the local HTTP server and return the non-blocking server instance."""
    global HOST
    init_db()
    s = get_settings()
    # Mode réseau : local (127.0.0.1) ou LAN (0.0.0.0)
    HOST, lan_safe = _lan_startup_safe(s)
    local_ip = _lan_get_local_ip()
    if HOST == "0.0.0.0":
        lan_note = (f"  Private LAN mode — http://{local_ip}:{PORT}\n"
                    f"  LAN access protected by code.\n"
                    f"  No internet access configured.")
    else:
        lan_note = ""
        if s.get("lan_mode") == "lan" and not lan_safe:
            lan_note = "  WARNING: LAN mode ignored (no secure code configured)."
    # Migration : img_unet (legacy) → img_unet_gguf si vide
    legacy_unet = s.get("img_unet", "").strip()
    if legacy_unet and not s.get("img_unet_gguf", "").strip():
        log.info(f"[Flux2] Migration img_unet → img_unet_gguf : {legacy_unet}")
        save_settings({"img_unet_gguf": legacy_unet})
        s["img_unet_gguf"] = legacy_unet

    # Migration de données v37.2 : si le dossier persistant est vide mais qu'un
    # ancien data local existe (build précédent), copier automatiquement.
    _local_data_src = os.path.join(CODE_ROOT, "data", "companion.db")
    _persistent_db  = DB_PATH
    if (not os.path.exists(_persistent_db) or os.path.getsize(_persistent_db) == 0)             and os.path.exists(_local_data_src) and os.path.getsize(_local_data_src) > 0             and os.path.abspath(_local_data_src) != os.path.abspath(_persistent_db):
        import shutil as _shutil
        log.info(f"[Migration v37.2] Old database detected: {_local_data_src}")
        try:
            os.makedirs(os.path.dirname(_persistent_db), exist_ok=True)
            _backup_db()  # sauvegarde de l'éventuel db existant
            _shutil.copy2(_local_data_src, _persistent_db)
            # Copier les médias
            for _subdir in ("images", "audio", "voices", "lora_previews"):
                _src_sub = os.path.join(CODE_ROOT, "data", _subdir)
                _dst_sub = os.path.join(DATA_DIR, _subdir)
                if os.path.isdir(_src_sub):
                    _shutil.copytree(_src_sub, _dst_sub, dirs_exist_ok=True)
            # Résumé
            import sqlite3 as _sq
            _conn = _sq.connect(_persistent_db)
            _n_chars = _conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
            _n_chats = _conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
            _n_msgs  = _conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            _conn.close()
            log.info(f"[Migration v37.2] Data migrated: {_n_chars} personnage(s), "
                     f"{_n_chats} conversation(s), {_n_msgs} message(s)")
            print("\n  AmiorAI data migration complete.")
            print(f"  Personnages : {_n_chars}  Conversations : {_n_chats}  Messages : {_n_msgs}")
            print(f"  Source kept: {_local_data_src}\n")
        except Exception as _me:
            log.error(f"[Migration v37.2] Failed: {_me}")

    # Migration : supprimer lan_access_code en clair si encore présent
    if s.get("lan_access_code", "").strip():
        log.warning("[LAN] Plain LAN code detected — removed. Regenerate a code from Settings.")
        save_settings({"lan_access_code": ""})
    log.info(f"{APP_NAME} demarre. HOST={HOST} DATA_ROOT={DATA_ROOT}")
    print(f"\n  {APP_NAME} {APP_VERSION} started.")
    print(f"  Open: http://127.0.0.1:{PORT}\n")
    if lan_note:
        print(lan_note)
    llm = s.get("lmstudio_model") or "(auto / loaded model)"
    img = s.get("image_model_path") or "(non configure)"
    print(f"  LM Studio model: {llm}")
    print(f"  Image model: {img}")
    print("  Configure LM Studio and ComfyUI in Settings.")
    print("  Models may load on first use; this can take a moment.")
    print(f"  Full log: {_log_path}\n")
    return ThreadingHTTPServer((HOST, PORT), Handler)


def main():
    """Command-line entry point used by start.bat and the optional Linux launcher."""
    server = start_server()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Arret.")
        log.info(f"{APP_NAME} arrete (KeyboardInterrupt).")
        server.shutdown()


if __name__ == "__main__":
    main()
