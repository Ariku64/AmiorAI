#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""
engine.py — local AI orchestration.

  - Text: LM Studio through its local OpenAI-compatible and native management APIs.
  - Image: a separately installed third-party ComfyUI instance through its local HTTP API.
    AmiorAI never installs, launches, restarts or terminates ComfyUI.

VRAM coordination swaps LM Studio, external ComfyUI and the optional CUDA TTS engine so only
the model required by the current task occupies the GPU. No LLM or TTS weights are
loaded inside the main AmiorAI Python process.
"""

import atexit
import logging
import json
import os
import random
import re
import subprocess
import threading
import time
import uuid
import urllib.request
import urllib.error
import urllib.parse

import model_manifests

import lmstudio_vram

# Logger fichier (herite des handlers configures par app.py::logging.basicConfig, donc ecrit
# aussi dans data/logs/app.log). Utilise pour distinguer explicitement les deux routes LLM :
# [conversation] pour le chat roleplay, [utility] pour les taches structurees (JSON, resumes,
# prompts image...), et [utility fallback -> conversation] si un repli explicite a lieu.
log = logging.getLogger("AmiorAI.engine")

# Chemins centralisés — source unique de vérité (app_paths.py).
# Plus de duplication entre engine.py et app.py.
from app_paths import CODE_ROOT, DATA_ROOT, WF_DIR, IMG_DIR, LOG_DIR, IS_FROZEN  # noqa: E402

ROOT = CODE_ROOT  # garde pour compatibilite avec le code existant ci-dessous

_LOCK = threading.RLock()
_tts = {"proc": None, "log": None}

# Shared LM Studio activity state exposed to the diagnostics UI.
_LLM_STATE = {"state": "idle", "started": 0.0, "finished": 0.0, "error": None,
              "gen_active": False, "gen_tokens": 0, "gen_started": 0.0}
_LLM_EVENTS = []
_LLM_EVENTS_LOCK = threading.Lock()
_LLM_MAX_EVENTS = 120

# Live ComfyUI generation state exposed to the diagnostics UI. This is a textual
# lifecycle (submit/queue/generate/download/complete/error), not a fabricated percent.
_COMFY_GEN_STATE = {
    "state": "idle", "stage": "idle", "prompt_id": None,
    "started": 0.0, "finished": 0.0, "error": None,
    "queue_running": 0, "queue_pending": 0, "message": "",
}
_COMFY_GEN_LOCK = threading.Lock()


def _set_comfy_generation_state(**values):
    with _COMFY_GEN_LOCK:
        _COMFY_GEN_STATE.update(values)


def comfy_generation_status(settings=None):
    """Return the latest ComfyUI generation lifecycle and live queue counts."""
    with _COMFY_GEN_LOCK:
        state = dict(_COMFY_GEN_STATE)
    now = time.time()
    started = float(state.get("started") or 0)
    finished = float(state.get("finished") or 0)
    endpoint = finished if finished and state.get("state") in ("complete", "error") else now
    state["elapsed"] = round(max(0.0, endpoint - started), 1) if started and state.get("state") != "idle" else 0
    if settings:
        try:
            base = _comfy_base(settings)
            with urllib.request.urlopen(base + "/queue", timeout=2) as resp:
                queue = json.loads(resp.read().decode("utf-8"))
            state["queue_running"] = len(queue.get("queue_running", []))
            state["queue_pending"] = len(queue.get("queue_pending", []))
            state["reachable"] = True
        except Exception as exc:  # status must never break the UI
            state["reachable"] = False
            state["probe_error"] = str(exc)
    return state


def _llm_log(kind, msg):
    """Append one bounded LM Studio activity event for the UI and logs."""
    with _LLM_EVENTS_LOCK:
        _LLM_EVENTS.append({"t": time.time(), "kind": kind, "msg": str(msg)[:400]})
        del _LLM_EVENTS[:-_LLM_MAX_EVENTS]


def _new_name(suffix="png"):
    return uuid.uuid4().hex[:12] + "." + suffix


def free_llm():
    """Compatibility no-op: AmiorAI no longer owns an in-process LLM."""
    _LLM_STATE.update(state="idle", started=0.0, finished=0.0, error=None,
                      gen_active=False, gen_tokens=0, gen_started=0.0)


def llm_status():
    """Return LM Studio request activity collected by AmiorAI."""
    st = dict(_LLM_STATE)
    now = time.time()
    if st.get("gen_active"):
        st["gen_elapsed"] = round(now - st.get("gen_started", now), 1)
    else:
        st["gen_elapsed"] = 0
    st["loaded"] = None  # actual loaded-state is supplied by lmstudio_vram status endpoints
    st["log_lines"] = []
    st["last_line"] = ""
    with _LLM_EVENTS_LOCK:
        st["events"] = list(_LLM_EVENTS)
    return st


def preload_llm(settings):
    """Load or confirm the configured conversation model in LM Studio."""
    with lmstudio_vram.vram_lock_for_text("conversation"):
        prepare_vram_for_lmstudio(settings, "conversation")
        return lmstudio_vram.ensure_loaded(settings, "conversation")


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


def _looks_like_transient_lmstudio_error(exc):
    msg = str(exc).lower()
    return any(x in msg for x in (
        "timed out", "timeout", "connection reset", "connection aborted",
        "remote end closed", "temporarily unavailable", "service unavailable",
        "not loaded", "loading", "model", "404", "409", "500", "502", "503", "504",
    ))


def _normalize_lmstudio_base(url):
    """Return the OpenAI-compatible LM Studio base URL, always ending in /v1."""
    base = (url or "http://127.0.0.1:1234/v1").strip().rstrip("/")
    if base.endswith("/api/v1"):
        base = base[:-len("/api/v1")]
    elif base.endswith("/v1"):
        return base
    return base + "/v1"


def _http_error_detail(exc):
    """Read an HTTP error body once so LM Studio's real validation message is visible."""
    try:
        raw = exc.read()
        if not raw:
            return ""
        text = raw.decode("utf-8", errors="replace").strip()
        try:
            payload = json.loads(text)
            err = payload.get("error", payload)
            if isinstance(err, dict):
                return str(err.get("message") or err.get("detail") or err)
            return str(err)
        except Exception:
            return text[:1200]
    except Exception:
        return ""


def _lmstudio_openai_models(settings):
    """List model IDs exposed by LM Studio's OpenAI-compatible /v1/models endpoint."""
    base = _normalize_lmstudio_base(settings.get("lmstudio_url"))
    req = urllib.request.Request(base + "/models")
    key = (settings.get("lmstudio_api_key") or "").strip()
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = _http_error_detail(e)
        raise RuntimeError(
            f"LM Studio returned HTTP {e.code} on {base}/models"
            + (f": {detail}" if detail else ".")
        ) from e
    except Exception as e:
        raise RuntimeError(
            f"LM Studio is unreachable at {base}. Start the Local Server in LM Studio. Details: {e}"
        ) from e
    items = payload.get("data") or payload.get("models") or []
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            mid = item.get("id") or item.get("name") or item.get("key")
        else:
            mid = str(item)
        if mid and mid not in out:
            out.append(str(mid))
    return out


def _resolve_lmstudio_openai_model(settings, configured_model, role):
    """Resolve a configured native/model key to the exact ID accepted by /chat/completions.

    LM Studio may expose a native model key in /api/v1/models and a loaded instance ID in
    /v1/models. Sending the native key directly can produce HTTP 400. This resolver always
    selects an ID actually advertised by the OpenAI endpoint.
    """
    available = _lmstudio_openai_models(settings)
    configured = (configured_model or "").strip()
    if not available:
        raise RuntimeError(
            "LM Studio is running but /v1/models exposes no loaded model. Load the "
            f"{role} model in LM Studio or configure its exact model key in AmiorAI."
        )
    if configured in available:
        return configured
    lower_map = {m.casefold(): m for m in available}
    if configured and configured.casefold() in lower_map:
        return lower_map[configured.casefold()]

    # Native API mapping: configured key/variant -> loaded instance ID exposed by OpenAI.
    if configured:
        try:
            for entry in lmstudio_vram.list_native_models(settings):
                if lmstudio_vram.model_matches(entry, configured):
                    instance_ids = [str(i.get("id")) for i in entry.get("loaded_instances", []) if i.get("id")]
                    for instance_id in instance_ids:
                        if instance_id in available:
                            return instance_id
                        if instance_id.casefold() in lower_map:
                            return lower_map[instance_id.casefold()]
        except Exception as e:  # native API is optional for the OpenAI call itself
            log.warning(f"[LM Studio] Native-to-OpenAI model mapping unavailable: {e}")

    # A single loaded model is unambiguous and is safer than sending an invalid placeholder.
    if len(available) == 1:
        resolved = available[0]
        if configured and configured != resolved:
            log.warning(
                f"[LM Studio] Configured {role} model '{configured}' is not exposed by /v1/models; "
                f"using the only loaded model '{resolved}'."
            )
        return resolved

    shown = ", ".join(available[:12])
    if configured:
        raise RuntimeError(
            f"The configured {role} model '{configured}' is not accepted by LM Studio. "
            f"Choose one of the IDs exposed by /v1/models: {shown}"
        )
    raise RuntimeError(
        f"Several models are loaded in LM Studio. Select the {role} model explicitly in AmiorAI: {shown}"
    )


def _extract_lmstudio_reply(payload):
    """Extract text from LM Studio/OpenAI-compatible response variants.

    Some reasoning-capable models return content as an array, while others expose
    the generated text in reasoning_content/reasoning or output_text.
    """
    choices = payload.get("choices") or [] if isinstance(payload, dict) else []
    if not choices:
        return "", {}
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = message.get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("value")
                if isinstance(text, str):
                    parts.append(text)
    for key in ("output_text", "text"):
        value = message.get(key) or choice.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    reply = "\n".join(x.strip() for x in parts if isinstance(x, str) and x.strip()).strip()
    if reply:
        return reply, message
    # Last-resort compatibility for reasoning models. This is preferable to falsely
    # reporting an empty transport response, but the caller may still retry with more tokens.
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key) or choice.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), message
    return "", message


def _lmstudio_chat(messages, settings, max_tokens, temp, stop, role="conversation"):
    """Send one non-streaming OpenAI-compatible chat request to LM Studio only."""
    base = _normalize_lmstudio_base(settings.get("lmstudio_url"))
    configured = settings.get("lmstudio_model") if role == "conversation" else (
        settings.get("llm_util_model") or settings.get("lmstudio_model")
    )
    model = _resolve_lmstudio_openai_model(settings, configured, role)
    url = base + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temp,
        "stream": False,
    }
    if stop:
        payload["stop"] = stop
    http_timeout = _setting_float(
        settings, "lmstudio_request_timeout", 600, min_value=30, max_value=7200,
    )
    retry_enabled = _setting_bool(settings, "lmstudio_retry_after_load_error", True)
    max_attempts = 2 if retry_enabled else 1
    last_error = None

    for attempt in range(1, max_attempts + 1):
        suffix = f" · attempt {attempt}/{max_attempts}" if max_attempts > 1 else ""
        _llm_log("request", f"LM Studio [{role}] · {model} @ {base} · {len(messages)} msg{suffix}")
        t0 = time.time()
        _LLM_STATE.update(state="ready", gen_active=True, gen_tokens=0, gen_started=t0, error=None)
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            key = (settings.get("lmstudio_api_key") or "").strip()
            if key:
                req.add_header("Authorization", "Bearer " + key)
            with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            choices = out.get("choices") or []
            if not choices:
                raise RuntimeError(f"LM Studio returned no choices: {out}")
            reply, message = _extract_lmstudio_reply(out)
            if not reply:
                finish = choices[0].get("finish_reason") if isinstance(choices[0], dict) else None
                raise RuntimeError(
                    "LM Studio returned no usable text"
                    + (f" (finish_reason={finish})" if finish else "")
                    + ". The selected model may spend the whole token budget on reasoning; "
                      "increase utility max tokens or choose a non-reasoning instruct model."
                )
            dur = round(time.time() - t0, 2)
            _LLM_STATE.update(gen_active=False)
            _llm_log("done", f"LM Studio response [{role}] · {dur} s")
            return reply
        except urllib.error.HTTPError as e:
            detail = _http_error_detail(e)
            last_error = RuntimeError(
                f"LM Studio rejected /v1/chat/completions with HTTP {e.code}"
                + (f": {detail}" if detail else f" ({e.reason})")
            )
        except Exception as e:  # noqa: BLE001
            last_error = e

        _LLM_STATE.update(gen_active=False)
        can_retry = attempt < max_attempts and _looks_like_transient_lmstudio_error(last_error)
        if can_retry:
            delay = _setting_float(settings, "lmstudio_post_load_delay", 4, min_value=0, max_value=60)
            _llm_log("warning", f"LM Studio request delayed/refused ({last_error}). Retrying after {delay:g} s.")
            try:
                lmstudio_vram.ensure_loaded(settings, role)
            except Exception as reload_error:  # noqa: BLE001
                log.warning(f"[VRAM] LM Studio revalidation before retry failed: {reload_error}")
            if delay > 0:
                time.sleep(delay)
            # The loaded instance ID may change after reload.
            model = _resolve_lmstudio_openai_model(settings, configured, role)
            payload["model"] = model
            continue
        _LLM_STATE.update(state="error", error=str(last_error))
        _llm_log("error", f"LM Studio request failed ({base}): {last_error}")
        raise RuntimeError(
            f"LM Studio request failed at {base}. Check the Local Server, selected model, and context size. "
            f"Details: {last_error}"
        ) from last_error

    raise RuntimeError(f"LM Studio request failed at {base}. Details: {last_error}")

def llm_util_chat(messages, settings, max_tokens=None, temperature=None, stop=None):
    """Route structured tasks to the optional utility model on the same LM Studio server."""
    util_enabled = _setting_bool(settings, "llm_util_enabled", False)
    if not util_enabled:
        log.info("[conversation] Utility model disabled; using the main LM Studio model.")
        return llm_chat(messages, settings, max_tokens=max_tokens, temperature=temperature, stop=stop)

    try:
        n_tok = int(float(max_tokens if max_tokens not in (None, "") else 800))
    except (TypeError, ValueError):
        n_tok = 800
    try:
        temp = float(temperature if temperature not in (None, "") else 0.7)
    except (TypeError, ValueError):
        temp = 0.7
    fallback = _setting_bool(settings, "llm_util_fallback", False)
    try:
        with lmstudio_vram.vram_lock_for_text("utility"):
            prepare_vram_for_lmstudio(settings, "utility")
            unload_conv_before = _setting_bool(settings, "lmstudio_unload_conversation_before_utility", True)
            unload_util_after = _setting_bool(settings, "lmstudio_unload_utility_after_use", True)
            shared = lmstudio_vram.roles_share_same_model(settings)
            if unload_conv_before and not shared:
                lmstudio_vram.unload_role_model(settings, "conversation")
            lmstudio_vram.ensure_loaded(settings, "utility")
            try:
                result = _lmstudio_chat(messages, settings, n_tok, temp, stop, role="utility")
                log.info(f"[utility] Task completed with LM Studio model: {settings.get('llm_util_model') or '(auto)'}")
                return result
            finally:
                if unload_util_after and not shared:
                    lmstudio_vram.unload_role_model(settings, "utility")
    except Exception as e:  # noqa: BLE001
        if fallback:
            log.warning(f"[utility fallback -> conversation] Utility LM Studio model unavailable ({e}).")
            return llm_chat(messages, settings, max_tokens=max_tokens, temperature=temperature, stop=stop)
        raise RuntimeError(
            "The LM Studio utility model is unavailable. Check its exact model ID in Settings. "
            f"Details: {e}"
        ) from e

def llm_chat(messages, settings, max_tokens=None, temperature=None, stop=None):
    """Main conversation route. Empty numeric settings fall back safely."""
    raw_tokens = max_tokens if max_tokens is not None else settings.get("llm_max_tokens", 400)
    try:
        n_tok = int(float(raw_tokens or 400))
    except (TypeError, ValueError):
        n_tok = 400
    n_tok = max(1, min(n_tok, 32768))
    if temperature is None:
        temp = _setting_float(settings, "llm_temperature", 0.85, min_value=0, max_value=2)
    else:
        try:
            temp = float(temperature or 0.85)
        except (TypeError, ValueError):
            temp = 0.85
    with lmstudio_vram.vram_lock_for_text("conversation"):
        prepare_vram_for_lmstudio(settings, "conversation")
        lmstudio_vram.ensure_loaded(settings, "conversation")
        return _lmstudio_chat(messages, settings, n_tok, temp, stop, role="conversation")


# --------------------------------------------------------------------------- #
#  ComfyUI tiers : connexion exclusive par API HTTP locale
# --------------------------------------------------------------------------- #
def _comfy_base(settings):
    return (settings.get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")


def _comfy_is_up(settings):
    base = _comfy_base(settings)
    for ep in ("/system_stats", "/"):
        try:
            with urllib.request.urlopen(base + ep, timeout=3):
                return True
        except Exception:
            continue
    return False



def _tts_vram_offload_enabled(settings):
    return _setting_bool(settings, "tts_vram_offload_enabled", True)


def _tts_should_use_cuda(settings, health=None):
    """Return whether the configured/running TTS engine may occupy CUDA VRAM."""
    if health and health.get("device"):
        return str(health.get("device")).lower().startswith("cuda")
    return (settings.get("tts_device") or "auto").strip().lower() != "cpu"


def _request_tts_shutdown(settings):
    """Ask an AmiorAI-compatible local TTS server to exit, including a manually launched one."""
    base = _tts_base(settings)
    req = urllib.request.Request(
        base + "/shutdown", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        response.read()


def _offload_tts_before_gpu_task(settings, target):
    """Release TTS CUDA VRAM before LM Studio or ComfyUI takes ownership of the GPU.

    Process termination is intentional: it is the only backend-independent way to guarantee
    that PyTorch has returned every CUDA allocation. The next spoken reply autostarts the
    selected embedded runtime and reloads its model. CPU TTS is left running.
    """
    if not _tts_vram_offload_enabled(settings):
        return False
    health = _tts_health(settings)
    process = _tts.get("proc")
    managed_running = bool(process and process.poll() is None)
    if health is None and not managed_running:
        return False
    if not _tts_should_use_cuda(settings, health):
        return False

    log.info("[VRAM] Releasing TTS CUDA model before %s", target)
    if managed_running:
        tts_stop()
    elif health is not None:
        try:
            _request_tts_shutdown(settings)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"[VRAM] The local TTS server could not release CUDA before {target}: {exc}. "
                "Stop the TTS server manually or disable TTS VRAM offload."
            ) from exc

    deadline = time.time() + 15.0
    while time.time() < deadline:
        if _tts_health(settings) is None:
            log.info("[VRAM] TTS CUDA process stopped; VRAM is available for %s", target)
            return True
        time.sleep(0.25)
    raise RuntimeError(
        f"[VRAM] The TTS server did not stop in time before {target}. "
        "Stop it manually and retry."
    )


def _unload_lmstudio_before_image(settings):
    """Release CUDA TTS and AmiorAI LM Studio models before image generation."""
    _offload_tts_before_gpu_task(settings, "ComfyUI image generation")
    try:
        lmstudio_vram.unload_amiorai_models(settings)
    except RuntimeError as e:
        # LM Studio est requis (backend actif ou utility sur le meme serveur) mais son API
        # native est inaccessible -> erreur claire remontee, jamais de fallback silencieux.
        raise RuntimeError(f"[VRAM] {e}")


def comfy_ensure(settings):
    """Require a separately installed third-party ComfyUI instance to be reachable."""
    if _comfy_is_up(settings):
        return
    base = _comfy_base(settings)
    raise RuntimeError(
        f"External ComfyUI is not reachable at {base}. "
        "Start ComfyUI from its own launcher, verify that its API is enabled, "
        "then check the ComfyUI address in AmiorAI Settings."
    )



def comfy_free(settings):
    """Demande a ComfyUI de decharger ses modeles (libere la VRAM pour le LLM). Si ComfyUI
    n'est pas joignable du tout, ne fait rien (rien a liberer) -- mais si ComfyUI REPOND et
    que /free echoue (erreur HTTP, refus), leve une RuntimeError claire plutot que d'avaler
    silencieusement l'erreur, pour que l'appelant puisse decider quoi en faire."""
    if not _comfy_is_up(settings):
        return
    base = _comfy_base(settings)
    data = json.dumps({"unload_models": True, "free_memory": True}).encode()
    req = urllib.request.Request(base + "/free", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"ComfyUI refused to release VRAM (/free): {e}")


def comfy_status(settings):
    return {
        "reachable": _comfy_is_up(settings),
        "external": True,
        "managed_by_app": False,
        "pid": None,
    }


def _comfy_vram(settings):
    """Lit /system_stats de ComfyUI pour connaitre l'etat VRAM du GPU qu'il utilise. Renvoie
    {name, total_mb, free_mb, used_mb, percent} ou None si injoignable / pas de GPU rapporte.
    Utilisee a la fois par le health check (Reglages -> Systeme) et par
    prepare_vram_for_lmstudio() pour confirmer qu'une liberation de VRAM a bien eu lieu."""
    base = _comfy_base(settings)
    try:
        with urllib.request.urlopen(base + "/system_stats", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    devices = data.get("devices") or []
    gpu = next((d for d in devices if d.get("type") == "cuda"), devices[0] if devices else None)
    if not gpu:
        return None
    total = gpu.get("vram_total")
    free = gpu.get("vram_free")
    if total is None or free is None:
        return None
    used = total - free

    def mb(n_bytes):
        return round(n_bytes / (1024 * 1024))

    return {
        "name": gpu.get("name", "GPU"),
        "total_mb": mb(total),
        "free_mb": mb(free),
        "used_mb": mb(used),
        "percent": round(100 * used / total) if total else 0,
    }


def _comfy_is_busy(settings):
    """Lit /queue de ComfyUI. Renvoie True si une generation tourne ou est en attente
    (queue_running ou queue_pending non vides), False si idle, None si /queue est
    inaccessible (ComfyUI probablement pas demarre -- pas occupe, juste absent)."""
    base = _comfy_base(settings)
    try:
        with urllib.request.urlopen(base + "/queue", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    running = data.get("queue_running") or []
    pending = data.get("queue_pending") or []
    return bool(running or pending)


def prepare_vram_for_lmstudio(settings, role):
    """Bascule VRAM ComfyUI -> LM Studio, symetrique de _unload_lmstudio_before_image (qui
    fait l'inverse avant une image). Appelee DEPUIS L'INTERIEUR d'un bloc
    `with lmstudio_vram.vram_lock_for_text(role):` pour que la sequence complete (liberation
    ComfyUI -> confirmation VRAM -> chargement LM Studio -> requete) reste atomique : une
    generation image ne peut jamais demarrer entre la liberation de ComfyUI et le chargement
    du modele LM Studio, puisque generate_t2i/i2i/group attendent le meme verrou.

    role : 'conversation' ou 'utility', utilise uniquement pour les logs.

    Comportement :
      - reglage comfy_vram_offload_before_lmstudio = false -> ne fait rien, comportement
        actuel conserve (point 5).
      - ComfyUI injoignable -> ne fait rien, ne bloque jamais LM Studio pour ca (point 14
        des criteres de validation : LM Studio doit pouvoir fonctionner sans ComfyUI).
      - ComfyUI occupe (image en cours) -> attend que la file soit vide, poll toutes les
        0.5s, jusqu'a 120s. Au-dela, leve une RuntimeError claire (point 15 : pas de perte
        silencieuse de la requete utilisateur).
      - ComfyUI idle -> appelle comfy_free(), verifie la liberation reelle de VRAM par
        polling (jusqu'a 15s), puis rend la main pour que LM Studio puisse charger."""
    # TTS has its own CUDA process. Stop it first so LM Studio can reload without an OOM.
    _offload_tts_before_gpu_task(settings, f"LM Studio {role}")

    offload_enabled = str(settings.get("comfy_vram_offload_before_lmstudio", "true")).lower() in ("true", "1", "yes")
    if not offload_enabled:
        return

    role_label = {"conversation": "conversation", "utility": "utility"}.get(role, role)

    # ComfyUI absent -> rien a liberer, LM Studio doit pouvoir fonctionner seul (critere 14).
    if not _comfy_is_up(settings):
        return

    # Wait until ComfyUI is idle; never call /free during an active generation.
    busy_wait_timeout = _setting_float(settings, "comfy_busy_wait_timeout", 180, min_value=10, max_value=3600)
    deadline = time.time() + busy_wait_timeout
    while True:
        busy = _comfy_is_busy(settings)
        if not busy:
            break
        if time.time() >= deadline:
            log.error(f"[VRAM] ComfyUI still busy after {busy_wait_timeout:g} s: text request canceled")
            raise RuntimeError(
                f"ComfyUI is still generating an image after {busy_wait_timeout:g} seconds. "
                "The text request was canceled instead of staying blocked indefinitely. "
                "Retry after the current generation finishes."
            )
        log.info(f"[VRAM] Text request {role_label} waiting: ComfyUI is still generating")
        time.sleep(0.5)

    # ComfyUI idle : libere sa VRAM.
    log.info(f"[VRAM] Releasing ComfyUI before reloading {role_label}")
    vram_before = _comfy_vram(settings)
    try:
        comfy_free(settings)
    except RuntimeError as e:
        log.error(f"[VRAM] {e}")
        raise

    # Confirm the release with light polling instead of a fixed blind sleep.
    release_timeout = _setting_float(settings, "comfy_vram_release_timeout", 30, min_value=2, max_value=300)
    poll_deadline = time.time() + release_timeout
    last_free = vram_before.get("free_mb") if vram_before else None
    stable_count = 0
    confirmed = False
    while time.time() < poll_deadline:
        time.sleep(0.5)
        vram_now = _comfy_vram(settings)
        if vram_now is None:
            continue
        now_free = vram_now.get("free_mb")
        if vram_before and last_free is not None:
            # Augmentation significative de VRAM libre (>= 200 Mo) : liberation confirmee.
            if now_free - (vram_before.get("free_mb") or 0) >= 200:
                freed = now_free - (vram_before.get("free_mb") or 0)
                log.info(f"[VRAM] ComfyUI released {freed} Mo de VRAM")
                confirmed = True
                break
            # Valeur stable sur 2 lectures successives : on considere que c'est termine
            # (le modele etait peut-etre deja petit, ou deja partiellement libere).
            if last_free is not None and now_free == last_free:
                stable_count += 1
                if stable_count >= 2:
                    log.info("[VRAM] ComfyUI VRAM stable, LM Studio reload allowed")
                    confirmed = True
                    break
            else:
                stable_count = 0
        last_free = now_free

    if not confirmed:
        log.warning(f"[VRAM] ComfyUI did not confirm release after {release_timeout:g} s, continuing carefully")
    # Dans tous les cas (confirme ou non), on rend la main : comfy_free() a deja ete appelee
    # avec succes plus haut, le polling n'est qu'une verification best-effort supplementaire.


# --------------------------------------------------------------------------- #
#  TTS local : Chatterbox Multilingual V3 par defaut, Qwen3-TTS optionnel
# --------------------------------------------------------------------------- #
# Chaque moteur utilise son propre environnement Python afin d'eviter les conflits
# de dependances (notamment transformers). Les anciens environnements XTTS `venv/`
# ne sont volontairement plus utilises a partir de la v40.
TTS_DIR = os.path.join(os.path.dirname(DATA_ROOT), "tts_server") if IS_FROZEN \
    else os.path.join(CODE_ROOT, "tts_server")
VOICE_DIR = os.path.join(DATA_ROOT, "voices")
os.makedirs(VOICE_DIR, exist_ok=True)


def _tts_base(settings):
    return (settings.get("tts_url") or "http://127.0.0.1:8810").rstrip("/")


def _tts_engine_name(settings):
    engine = (settings.get("tts_engine") or "chatterbox").strip().lower()
    return engine if engine in ("chatterbox", "qwen") else "chatterbox"


def _tts_health(settings):
    """Interroge /health. Renvoie le dict du serveur, ou None si injoignable."""
    base = _tts_base(settings)
    try:
        with urllib.request.urlopen(base + "/health", timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _tts_is_up(settings):
    h = _tts_health(settings)
    expected = _tts_engine_name(settings)
    return bool(h and h.get("status") in ("ready", "loading") and h.get("engine") == expected)


def tts_status(settings):
    p = _tts.get("proc")
    ours = bool(p and p.poll() is None)
    h = _tts_health(settings)
    expected = _tts_engine_name(settings)
    running = (h or {}).get("engine")
    mismatch = bool(h and running and running != expected)
    return {
        "reachable": h is not None,
        "managed_by_app": ours,
        "pid": (p.pid if ours else None),
        "model_status": (h or {}).get("status", "offline"),
        "device": (h or {}).get("device"),
        "engine": running,
        "configured_engine": expected,
        "engine_mismatch": mismatch,
        "model": (h or {}).get("model"),
        "error": ((f"Running engine '{running}' does not match configured engine '{expected}'. Restart TTS."
                   if mismatch else None) or (h or {}).get("error")),
    }


def _tts_python_for_engine(tpath, engine):
    """Resolve the dedicated runtime. Windows v40.0.2 uses official embeddable Python."""
    if os.name == "nt":
        runtime_name = "python_qwen" if engine == "qwen" else "python_chatterbox"
        return os.path.join(tpath, runtime_name, "python.exe"), runtime_name
    # Linux/macOS keep isolated virtual environments because CPython does not publish an
    # equivalent embeddable distribution for those platforms.
    runtime_name = "venv_qwen" if engine == "qwen" else "venv_chatterbox"
    return os.path.join(tpath, runtime_name, "bin", "python"), runtime_name


def _tts_probe_runtime_module(python, engine):
    """Verify that the selected embedded runtime really contains its TTS package.

    A Windows embeddable runtime may exist after an interrupted installer even when
    its package installation never completed.  Probe with that exact interpreter
    before starting Flask so the user receives a repair instruction instead of a
    delayed ``No module named ...`` error from /health.
    """
    module = "qwen_tts" if engine == "qwen" else "chatterbox"
    package = "qwen-tts" if engine == "qwen" else "chatterbox-tts"
    code = (
        "import importlib.util, importlib.metadata, sys; "
        f"spec=importlib.util.find_spec({module!r}); "
        "sys.exit(3) if spec is None else None; "
        f"print(importlib.metadata.version({package!r}))"
    )
    try:
        result = subprocess.run(
            [python, "-c", code], capture_output=True, text=True,
            timeout=20, creationflags=(0x08000000 if os.name == "nt" else 0),
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    detail = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, detail


def _tts_start_timeout(settings):
    """Retourne le delai maximal de chargement du moteur, avec une borne sure."""
    try:
        return max(60, int(float(settings.get("tts_start_timeout", 900) or 900)))
    except (TypeError, ValueError):
        return 900


def _tts_wait_until_ready(settings, expected, timeout, proc=None):
    """Attend qu'un serveur deja lance ou nouvellement cree soit reellement pret."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        h = _tts_health(settings)
        if h:
            running_engine = h.get("engine")
            if running_engine and running_engine != expected:
                raise RuntimeError(
                    f"Le serveur TTS utilise '{running_engine}' au lieu de '{expected}'. "
                    "Redemarre le moteur vocal depuis les reglages."
                )
            status = h.get("status")
            if status == "ready":
                return
            if status == "error":
                raise RuntimeError(
                    f"Le moteur TTS '{expected}' a signale une erreur : "
                    f"{h.get('error') or 'cause inconnue'}. Consulte data/logs/tts_server.log."
                )
            if status not in ("loading", None):
                raise RuntimeError(
                    f"Le serveur TTS repond avec un etat inconnu : {status!r}. "
                    "Arrete-le avant de relancer le moteur vocal."
                )
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(
                "Le serveur TTS s'est arrete au demarrage. Consulte data/logs/tts_server.log. "
                "La cause la plus frequente est un environnement vocal non installe ou incomplet."
            )
        time.sleep(2.0)
    raise RuntimeError(
        "Le moteur TTS n'a pas fini de charger dans le delai imparti. "
        "Consulte data/logs/tts_server.log et augmente le delai de demarrage si le telechargement continue."
    )


def tts_ensure(settings):
    """S'assure que le moteur TTS configure est pret, sinon le lance en arriere-plan."""
    expected = _tts_engine_name(settings)
    h = _tts_health(settings)
    if h:
        running_engine = h.get("engine")
        if running_engine and running_engine != expected:
            # Un moteur lance par AmiorAI peut etre remplace automatiquement apres un changement
            # de reglage. Un serveur externe doit etre arrete manuellement pour eviter de tuer un
            # processus qui n'appartient pas a l'application.
            p = _tts.get("proc")
            if p and p.poll() is None:
                tts_stop()
                time.sleep(1.0)
            else:
                raise RuntimeError(
                    f"Le port TTS est deja utilise par le moteur '{running_engine}'. "
                    f"Arrete ce serveur puis redemarre le moteur '{expected}'."
                )
        elif h.get("status") == "ready":
            return
        elif h.get("status") == "loading":
            # Ne pas envoyer /tts tant que le modele charge : le serveur renverrait 503.
            p = _tts.get("proc")
            managed = p if p and p.poll() is None else None
            _tts_wait_until_ready(settings, expected, _tts_start_timeout(settings), managed)
            return
        elif h.get("status") == "error":
            server_error = h.get("error") or "cause inconnue"
            missing_module = (
                (expected == "chatterbox" and "No module named 'chatterbox'" in server_error)
                or (expected == "qwen" and "No module named 'qwen_tts'" in server_error)
            )
            if missing_module:
                installer = "repair_chatterbox.bat" if expected == "chatterbox" else "install_qwen.bat"
                raise RuntimeError(
                    f"Le runtime TTS est incomplet : {server_error}. Ferme AmiorAI puis lance "
                    f"tts_server\\{installer}; le Python Embedded sera repare sans Python systeme."
                )
            raise RuntimeError(
                f"Le moteur TTS '{expected}' est demarre mais en erreur : {server_error}. "
                "Consulte data/logs/tts_server.log puis utilise Redemarrer TTS."
            )
        else:
            raise RuntimeError(
                "Un serveur repond sur le port TTS, mais son etat est inconnu. "
                "Arrete-le avant de relancer le moteur vocal."
            )

    autolaunch = str(settings.get("tts_autolaunch", "true")).lower() in ("1", "true", "yes", "oui")
    if not autolaunch:
        raise RuntimeError("Le serveur TTS n'est pas demarre. Active 'Lancer automatiquement' ou lance-le a la main.")

    tpath = (settings.get("tts_path") or TTS_DIR).strip()
    script = os.path.join(tpath, "tts_server.py")
    if not os.path.exists(script):
        raise RuntimeError(
            f"tts_server.py introuvable dans {tpath}. Reinstalle le dossier tts_server de la v40."
        )

    python, env_name = _tts_python_for_engine(tpath, expected)
    if not os.path.exists(python):
        installer = "install_qwen.bat" if expected == "qwen" else "install.bat"
        shell_installer = "install_qwen.sh" if expected == "qwen" else "install.sh"
        raise RuntimeError(
            f"Runtime TTS autonome '{env_name}' introuvable. Lance {installer} sous Windows "
            f"ou {shell_installer} sous Linux/macOS dans tts_server/. Aucun Python systeme n'est requis sous Windows."
        )

    runtime_ok, runtime_detail = _tts_probe_runtime_module(python, expected)
    if not runtime_ok:
        installer = "install_qwen.bat" if expected == "qwen" else "repair_chatterbox.bat"
        module = "qwen_tts" if expected == "qwen" else "chatterbox"
        detail = f" Detail: {runtime_detail}" if runtime_detail else ""
        raise RuntimeError(
            f"Le runtime TTS '{env_name}' existe, mais le module '{module}' n'y est pas installe. "
            f"L'installation a probablement ete interrompue. Ferme AmiorAI puis lance "
            f"tts_server\\{installer}; le runtime sera repare sans Python systeme.{detail}"
        )

    base = _tts_base(settings)
    port = urllib.parse.urlparse(base).port or 8810
    device = (settings.get("tts_device") or "auto").strip()
    model = (settings.get("tts_qwen_model") or "Qwen/Qwen3-TTS-12Hz-0.6B-Base").strip() \
        if expected == "qwen" else "v3"
    args = [python, script, "--port", str(port), "--device", device,
            "--engine", expected, "--model", model]

    creationflags = 0
    if os.name == "nt":
        creationflags = 0x08000000  # CREATE_NO_WINDOW

    logpath = os.path.join(LOG_DIR, "tts_server.log")
    if _tts.get("log"):
        try:
            _tts["log"].close()
        except Exception:
            pass
    _tts["log"] = open(logpath, "w", encoding="utf-8", errors="replace")
    _tts["proc"] = subprocess.Popen(
        args, cwd=tpath, stdout=_tts["log"], stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )

    # Le premier lancement telecharge les poids. La valeur v40 par defaut est 900 s.
    _tts_wait_until_ready(
        settings, expected, _tts_start_timeout(settings), _tts["proc"]
    )


def tts_stop():
    p = _tts.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
        except Exception:
            pass
    _tts["proc"] = None
    if _tts.get("log"):
        try:
            _tts["log"].close()
        except Exception:
            pass
        _tts["log"] = None


def tts_kill(settings):
    p = _tts.get("proc")
    if p and p.poll() is None:
        try:
            p.kill()
        except Exception:
            pass
    tts_stop()
    return {"ok": True, "msg": "Process TTS arrete (kill)."}


def prepare_vram_for_tts(settings):
    """Give the CUDA GPU to TTS by unloading LM Studio and freeing idle ComfyUI models."""
    if not _tts_vram_offload_enabled(settings) or not _tts_should_use_cuda(settings):
        return

    try:
        lmstudio_vram.unload_amiorai_models(settings)
    except RuntimeError as exc:
        # A stopped LM Studio server must not prevent standalone speech. If it is reachable but
        # its native API fails, preserve the clear error because VRAM ownership is uncertain.
        message = str(exc).lower()
        if "unreachable" in message or "connection" in message or "refused" in message:
            log.info("[VRAM] LM Studio unavailable while preparing TTS; continuing standalone")
        else:
            raise RuntimeError(f"[VRAM] Unable to release LM Studio before TTS: {exc}") from exc

    if not _comfy_is_up(settings):
        return
    busy_timeout = _setting_float(settings, "comfy_busy_wait_timeout", 180, min_value=10, max_value=3600)
    deadline = time.time() + busy_timeout
    while _comfy_is_busy(settings):
        if time.time() >= deadline:
            raise RuntimeError(
                f"ComfyUI is still generating after {busy_timeout:g} seconds. "
                "Voice generation was canceled to avoid corrupting the active image task."
            )
        time.sleep(0.5)
    comfy_free(settings)
    log.info("[VRAM] ComfyUI models released before TTS")


def tts_start(settings, force=True):
    if _tts_is_up(settings):
        return {"ok": True, "msg": "Le moteur TTS configure repond deja."}
    s = dict(settings)
    if force:
        s["tts_autolaunch"] = "true"
    with lmstudio_vram.vram_lock_for_text("tts"):
        prepare_vram_for_tts(s)
        tts_ensure(s)
    return {"ok": True, "msg": f"Serveur TTS demarre ({_tts_engine_name(s)})."}


def tts_restart(settings):
    tts_kill(settings)
    time.sleep(1.5)
    return tts_start(settings, force=True)


def tts_speak(text, speaker_wav_path, settings, language="fr", speed=1.0, reference_text=""):
    """Genere un WAV dans data/audio avec le moteur TTS configure."""
    if not text or not text.strip():
        raise RuntimeError("Empty text.")
    if not speaker_wav_path or not os.path.exists(speaker_wav_path):
        raise RuntimeError("No voice sample for this character. Import an audio sample "
                           "in its profile (Voice section).")
    with lmstudio_vram.vram_lock_for_text("tts"):
        prepare_vram_for_tts(settings)
        with _LOCK:
            tts_ensure(settings)
            base = _tts_base(settings)
            payload = json.dumps({
                "text": text.strip(),
                "language": language,
                "speaker_wav": speaker_wav_path,
                "reference_text": (reference_text or "").strip(),
                "speed": speed,
                "exaggeration": settings.get("tts_exaggeration", "0.5"),
                "cfg_weight": settings.get("tts_cfg_weight", "0.5"),
                "temperature": settings.get("tts_temperature", "0.8"),
            }).encode("utf-8")
            req = urllib.request.Request(base + "/tts", data=payload,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    audio_bytes = resp.read()
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                raise RuntimeError(f"TTS server error: {detail}")
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"Serveur TTS injoignable : {e}")

    if len(audio_bytes) < 44 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        raise RuntimeError(
            "Le serveur TTS a repondu, mais le contenu recu n'est pas un fichier WAV valide. "
            "Consulte data/logs/tts_server.log puis redemarre le moteur vocal."
        )

    audio_dir = os.path.join(DATA_ROOT, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    fname = f"tts_{uuid.uuid4().hex[:10]}.wav"
    fpath = os.path.join(audio_dir, fname)
    with open(fpath, "wb") as f:
        f.write(audio_bytes)
    return fname


atexit.register(tts_stop)


# --------------------------------------------------------------------------- #
#  Whisper local (reconnaissance vocale, dictee) - charge dans CE process
#  comme le LLM, via faster-whisper (CTranslate2, leger et rapide CPU/GPU)
# --------------------------------------------------------------------------- #
_WHISPER = {"model": None, "size": None}


def _get_whisper(settings):
    size = (settings.get("whisper_model_size") or "small").strip()
    with _LOCK:
        if _WHISPER["model"] is not None and _WHISPER["size"] == size:
            return _WHISPER["model"]
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper is not installed. In the app environment: "
                "pip install faster-whisper (see README, Voice section)."
            )
        device = (settings.get("whisper_device") or "auto").strip()
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        _llm_log("info", f"Chargement Whisper ({size}, {device})…") if False else None
        model = WhisperModel(size, device=device, compute_type=compute_type)
        _WHISPER["model"] = model
        _WHISPER["size"] = size
        return model


def whisper_transcribe(audio_path, settings, language=None):
    """Transcrit un fichier audio en texte. language=None -> detection auto."""
    if not os.path.exists(audio_path):
        raise RuntimeError("Audio file not found.")
    model = _get_whisper(settings)
    lang = (language or settings.get("whisper_language") or "").strip() or None
    segments, info = model.transcribe(audio_path, language=lang, beam_size=5, vad_filter=True)
    text = "".join(seg.text for seg in segments).strip()
    return {"text": text, "language": info.language, "language_probability": round(info.language_probability, 2)}


def whisper_status():
    return {"loaded": _WHISPER["model"] is not None, "size": _WHISPER["size"]}


# --------------------------------------------------------------------------- #
#  ComfyUI : generation via API HTTP (injection de jetons dans le workflow)
# --------------------------------------------------------------------------- #
def _json_escape(s):
    return json.dumps(s)[1:-1]


RESOLUTIONS = {
    "512x512":   (512, 512),      # interne : aperçus rapides (templates/LoRA) Krea 2
    "1024x1024": (1024, 1024),
    "832x1216":  (832, 1216),
    "768x1344":  (768, 1344),
    "1344x768":  (1344, 768),
    "1216x832":  (1216, 832),
}


def _comfy_randomize_seeds(workflow, fixed=None):
    """Randomise tous les champs seed/noise_seed du workflow. Si fixed est fourni, utilise cette graine."""
    seed_val = fixed if fixed is not None else random.randint(0, 2_147_483_646)
    for node in workflow.values():
        inputs = node.get("inputs", {})
        for key in ("seed", "noise_seed"):
            if key in inputs and not isinstance(inputs[key], list):
                inputs[key] = seed_val
    return workflow, seed_val


def _comfy_inject(raw_text, prompt, settings, negative=None, image_name=None, family=None,
                   wf_name=""):
    txt = raw_text
    txt = txt.replace(settings.get("prompt_token", "%PROMPT%"), _json_escape(prompt))
    neg = negative if negative is not None else settings.get("default_negative", "")
    txt = txt.replace(settings.get("negative_token", "%NEGATIVE%"), _json_escape(neg))
    if image_name is not None:
        txt = txt.replace(settings.get("image_token", "%IMAGE%"), _json_escape(image_name))
    wf = json.loads(txt)

    # --- Injecter la resolution choisie dans les PrimitiveInt width/height ---
    res_str = settings.get("image_resolution", "1024x1024")
    w, h = RESOLUTIONS.get(res_str, (1024, 1024))
    for node in wf.values():
        meta = node.get("_meta", {}).get("title", "").lower()
        inp = node.get("inputs", {})
        if node.get("class_type") == "PrimitiveInt":
            if meta == "width" and isinstance(inp.get("value"), int) and not isinstance(inp.get("value"), list):
                inp["value"] = w
            elif meta == "height" and isinstance(inp.get("value"), int) and not isinstance(inp.get("value"), list):
                inp["value"] = h
        # SD1.5/SDXL utilisent un EmptyLatentImage classique (width/height en inputs directs,
        # pas via PrimitiveInt) -> gere aussi ce cas pour que la resolution s'applique.
        if node.get("class_type") == "EmptyLatentImage":
            if "width" in inp and not isinstance(inp["width"], list):
                inp["width"] = w
            if "height" in inp and not isinstance(inp["height"], list):
                inp["height"] = h

    family_id = (family or settings.get("image_family") or "flux2_klein").strip()
    _inject_models_for_family(wf, settings, family_id)

    if family_id == "krea2":
        # Pipeline Krea 2 : ResolutionSelector optionnel + sampler paramétrable +
        # slots LoRA dédiés (personnage/utilitaire), jamais la pile LoRA globale.
        wf = _inject_krea2_resolution_selector(wf, settings)
        wf = _inject_krea2_sampler(wf, settings)
        return _inject_krea2_loras(wf, settings, wf_name=wf_name)

    return _inject_loras_via_slot(wf, prompt, settings, family_id, wf_name=wf_name)




def _inject_krea2_resolution_selector(wf, settings):
    """Inject Krea 2 ResolutionSelector values when the workflow exposes that node.

    Fallback: if no ResolutionSelector node exists, continue to drive EmptyLatentImage
    with the generic image_resolution setting so the workflow remains compatible.
    """
    aspect_ratio = (settings.get("krea2_aspect_ratio") or "2:3 (Portrait Photo)").strip()
    try:
        megapixels = float(settings.get("krea2_megapixels", "2") or "2")
    except (TypeError, ValueError):
        megapixels = 2.0
    try:
        multiple = int(float(settings.get("krea2_multiple", "8") or "8"))
    except (TypeError, ValueError):
        multiple = 8
    multiple = max(1, min(multiple, 128))
    used_selector = False
    for node in wf.values():
        if node.get("class_type") == "ResolutionSelector":
            inp = node.get("inputs", {})
            if "aspect_ratio" in inp and not isinstance(inp["aspect_ratio"], list):
                inp["aspect_ratio"] = aspect_ratio
            if "megapixels" in inp and not isinstance(inp["megapixels"], list):
                inp["megapixels"] = megapixels
            if "multiple" in inp and not isinstance(inp["multiple"], list):
                inp["multiple"] = multiple
            used_selector = True
    return wf

def _inject_models_for_family(wf, settings, family_id):
    """Injecte les modèles selon la famille de workflow.

    Pour flux2_klein : respecte flux2_loader_mode (gguf | safetensors).
      - Mode GGUF : injecte img_unet_gguf dans UnetLoaderGGUF uniquement.
      - Mode Safetensors : injecte img_unet_safetensors dans UNETLoader uniquement.
      - CLIP et VAE : injectés dans les deux modes (inchangé).
      - Ne jamais injecter un .gguf dans UNETLoader ni l'inverse.
    """
    if family_id == "flux2_klein" or family_id not in model_manifests.FAMILIES:
        clip      = settings.get("img_clip", "").strip()
        clip_type = settings.get("img_clip_type", "flux2").strip()
        vae       = settings.get("img_vae", "").strip()
        mode      = settings.get("flux2_loader_mode", "gguf").strip()

        # Résoudre l'UNet selon le mode actif (fallback img_unet pour compat héritage)
        if mode == "safetensors":
            unet_sf = settings.get("img_unet_safetensors", "").strip()
        else:
            # GGUF : img_unet_gguf prioritaire, img_unet en fallback (héritage)
            unet_sf = ""
            unet_gguf = settings.get("img_unet_gguf", "").strip() or settings.get("img_unet", "").strip()

        for node in wf.values():
            ct  = node.get("class_type", "")
            inp = node.get("inputs", {})

            if ct == "UnetLoaderGGUF":
                if mode == "gguf" and unet_gguf:
                    inp["unet_name"] = unet_gguf
                # Mode safetensors : ne rien écrire dans UnetLoaderGGUF
                # (le workflow _st.json ne contient pas ce loader de toute façon)

            elif ct == "UNETLoader":
                if mode == "safetensors":
                    # Validation : refuser un .gguf dans le loader Safetensors
                    if unet_sf.lower().endswith(".gguf"):
                        raise RuntimeError(
                            "Safetensors mode: the selected model is a GGUF file "
                            f"({unet_sf}). Select a .safetensors file in Image Studio or Settings.")
                    if unet_sf:
                        inp["unet_name"] = unet_sf
                    # Injecter weight_dtype depuis le réglage (défaut : "default")
                    weight_dtype = settings.get("flux2_safetensors_weight_dtype", "default").strip() or "default"
                    inp["weight_dtype"] = weight_dtype
                # Mode gguf : ne rien écrire dans UNETLoader

            elif ct in ("CLIPLoader", "DualCLIPLoader") and clip:
                inp["clip_name"] = clip
                if clip_type:
                    inp["type"] = clip_type

            elif ct == "VAELoader" and vae:
                inp["vae_name"] = vae

        return wf

    family = model_manifests.FAMILIES[family_id]
    if family_id == "krea2":
        krea_unet = (settings.get("krea2_unet") or "").strip()
        if krea_unet and not krea_unet.lower().endswith(".safetensors"):
            raise RuntimeError(
                "Krea 2 requires a .safetensors diffusion model for UNETLoader. "
                f"Selected value: {krea_unet}"
            )
    # IDs des nodes qui are declared LoRA slots — never overwrite them
    lora_slot_ids = set()
    for wf_key, wf_manifest in model_manifests.WORKFLOW_REGISTRY.items():
        for slot in model_manifests.get_lora_slots_from_manifest(wf_manifest):
            lora_slot_ids.add(str(slot["node_id"]))

    for comp in family["components"]:
        kind = comp["kind"]
        setting_key = comp["setting"]
        if comp.get("multi"):
            continue
        value = (settings.get(setting_key) or "").strip()
        if not value:
            continue
        node_types = model_manifests.NODE_TYPES_BY_KIND.get(kind, ())
        for nid, node in wf.items():
            if nid in lora_slot_ids:
                continue
            ct = node.get("class_type", "")
            if ct not in node_types:
                continue
            inp = node.get("inputs", {})
            for field in ("ckpt_name", "unet_name", "clip_name", "vae_name", "lora_name", "control_net_name"):
                if field in inp:
                    strict = family_id == "krea2"
                    value = _resolve_comfy_choice(
                        settings, ct, field, value,
                        label=f"{family_id} {comp.get('label', kind)}",
                        strict=strict,
                    )
                    inp[field] = value
                    break
    return wf


def resolve_flux2_workflow_variant(base_name: str, settings: dict) -> str:
    """Résolveur central Flux 2 Klein — à utiliser pour TOUTES les générations de cette famille.
    base_name : forme de base du workflow, ex 't2i.json', 'i2i.json', 'duo.json'...
                (avec ou sans suffixe _st — sera normalisé avant résolution)
    Mode gguf        → workflow sans suffixe _st  (ex: 'duo.json')
    Mode safetensors → workflow avec suffixe _st  (ex: 'duo_st.json')
    Lève RuntimeError si le modèle requis pour le mode actif n'est pas configuré,
    ou si le fichier workflow résolu est introuvable sur disque."""
    # Normaliser la base : supprimer _st si déjà présent, extraire le nom de base
    stem = base_name.replace(".json", "").removesuffix("_st")
    mode = settings.get("flux2_loader_mode", "gguf").strip()

    # Utiliser la table centralisée dans model_manifests (source unique de vérité)
    variant_map = model_manifests.FLUX2_WORKFLOW_VARIANTS.get(mode, {})
    resolved = variant_map.get(stem)

    if not resolved:
        # Stem inconnu de la table → fallback sur convention de nommage
        resolved = f"{stem}_st.json" if mode == "safetensors" else f"{stem}.json"

    if mode == "safetensors":
        unet = settings.get("img_unet_safetensors", "").strip()
        if not unet:
            log.error("[Flux2] Safetensors mode is active but img_unet_safetensors is empty.")
            raise RuntimeError(
                "Safetensors mode: no UNet configured. "
                "Scan your diffusion_models folder in Library, "
                "then select the .safetensors file in Image Studio (UNet Safetensors section).")
    else:
        unet = settings.get("img_unet_gguf", "").strip() or settings.get("img_unet", "").strip()
        if not unet:
            log.error("[Flux2] GGUF mode is active but img_unet_gguf is empty.")
            raise RuntimeError(
                "GGUF mode: no UNet configured. "
                "Scan your diffusion_models folder in Library, "
                "then select the .gguf file in Image Studio (UNet GGUF section).")

    # Vérifier que le fichier workflow existe
    wf_path = os.path.join(WF_DIR, resolved)
    if not os.path.exists(wf_path):
        raise RuntimeError(
            f"Workflow {resolved} not found (mode {'Safetensors' if mode == 'safetensors' else 'GGUF'} "
            f"pour '{base_name}'). Make sure the file exists in the workflows/ folder.")

    # Validation Safetensors : vérifier que le workflow contient bien UNETLoader + weight_dtype
    if mode == "safetensors":
        import json as _json
        try:
            wf_check = _json.loads(open(wf_path, "r", encoding="utf-8").read())
            has_unet_loader = any(
                n.get("class_type") == "UNETLoader" for n in wf_check.values()
            )
            has_weight_dtype = any(
                n.get("class_type") == "UNETLoader" and "weight_dtype" in n.get("inputs", {})
                for n in wf_check.values()
            )
            has_gguf_loader = any(
                n.get("class_type") == "UnetLoaderGGUF" for n in wf_check.values()
            )
            if not has_unet_loader:
                raise RuntimeError(
                    f"Safetensors workflow {resolved} does not contain an UNETLoader node. "
                    "Recreate this workflow from ComfyUI.")
            if not has_weight_dtype:
                raise RuntimeError(
                    f"Safetensors workflow {resolved} does not contain the required weight_dtype input "
                    "in UNETLoader. Update this workflow.")
            if has_gguf_loader:
                raise RuntimeError(
                    f"Safetensors workflow {resolved} still contains a UnetLoaderGGUF node. "
                    "Recreate this workflow without the GGUF loader.")
        except (ValueError, OSError) as e:
            raise RuntimeError(f"Unable to validate workflow {resolved} : {e}")

    return resolved


# Alias interne pour compatibilité avec les appels existants dans ce module
_flux2_workflow = resolve_flux2_workflow_variant


def comfy_unet_loader_info(settings):
    """Interroge ComfyUI /object_info/UNETLoader pour obtenir les valeurs autorisées
    de weight_dtype et la valeur par défaut. Retourne un dict ou None si inaccessible."""
    base = (settings.get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")
    try:
        import urllib.request
        with urllib.request.urlopen(f"{base}/object_info/UNETLoader", timeout=5) as r:
            import json as _json
            info = _json.loads(r.read())
        node = info.get("UNETLoader", {})
        inputs = node.get("input", {}).get("required", {})
        dtype_info = inputs.get("weight_dtype", [])
        if isinstance(dtype_info, list) and dtype_info:
            allowed = dtype_info[0] if isinstance(dtype_info[0], list) else []
            default = dtype_info[1].get("default", allowed[0] if allowed else "default") if len(dtype_info) > 1 else (allowed[0] if allowed else "default")
        else:
            allowed = ["default", "fp8_e4m3fn", "fp8_e5m2", "fp16", "bf16"]
            default = "default"
        return {"allowed": allowed, "default": default}
    except Exception as e:
        log.warning(f"[Flux2-ST] Impossible de lire /object_info/UNETLoader : {e}")
        return None


_COMFY_CHOICES_CACHE = {}


def comfy_input_choices(settings, node_type, input_name, max_age=15):
    """Return the exact list of values accepted by one ComfyUI loader input."""
    base = _comfy_base(settings)
    cache_key = (base, node_type, input_name)
    cached = _COMFY_CHOICES_CACHE.get(cache_key)
    if cached and time.time() - cached[0] <= max_age:
        return list(cached[1])
    try:
        with urllib.request.urlopen(f"{base}/object_info/{node_type}", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        node = data.get(node_type, {})
        inputs = node.get("input", {})
        spec = (inputs.get("required", {}).get(input_name)
                or inputs.get("optional", {}).get(input_name)
                or [])
        choices = spec[0] if isinstance(spec, list) and spec and isinstance(spec[0], list) else []
        choices = [str(v) for v in choices]
        _COMFY_CHOICES_CACHE[cache_key] = (time.time(), choices)
        return choices
    except Exception as e:
        log.warning(f"[ComfyUI] Unable to read choices for {node_type}.{input_name}: {e}")
        return []


def _portable_model_name(value):
    return (value or "").strip().replace("\\", "/").lstrip("./")


def _resolve_comfy_choice(settings, node_type, input_name, selected, label="model", strict=False):
    """Resolve an absolute/catalog path to the exact value accepted by ComfyUI.

    The model catalog can store paths such as ``models/diffusion_models/name.safetensors``
    while loader nodes often expose only ``name.safetensors``. Sending the catalog path
    verbatim triggers ``value_not_in_list``. This function compares exact paths, normalized
    paths, known model-root suffixes, and finally a unique basename.
    """
    selected = (selected or "").strip()
    if not selected:
        return selected
    choices = comfy_input_choices(settings, node_type, input_name)
    if not choices:
        # Safe offline fallback. Runtime validation will still be performed by ComfyUI.
        normalized = _portable_model_name(selected)
        for marker in ("models/diffusion_models/", "models/unet/", "models/clip/",
                       "models/text_encoders/", "models/vae/", "models/loras/",
                       "diffusion_models/", "unet/", "clip/", "text_encoders/", "vae/", "loras/"):
            idx = normalized.casefold().find(marker.casefold())
            if idx >= 0:
                normalized = normalized[idx + len(marker):]
                break
        return normalized

    if selected in choices:
        return selected
    selected_norm = _portable_model_name(selected)
    choice_norm_map = {_portable_model_name(v).casefold(): v for v in choices}
    if selected_norm.casefold() in choice_norm_map:
        return choice_norm_map[selected_norm.casefold()]

    suffixes = [selected_norm]
    for marker in ("models/diffusion_models/", "models/unet/", "models/clip/",
                   "models/text_encoders/", "models/vae/", "models/loras/",
                   "diffusion_models/", "unet/", "clip/", "text_encoders/", "vae/", "loras/"):
        idx = selected_norm.casefold().find(marker.casefold())
        if idx >= 0:
            suffixes.append(selected_norm[idx + len(marker):])
    for suffix in suffixes:
        match = choice_norm_map.get(suffix.casefold())
        if match:
            log.info(f"[ComfyUI] Resolved {label}: '{selected}' -> '{match}'")
            return match

    basename = selected_norm.rsplit("/", 1)[-1].casefold()
    basename_matches = [v for v in choices if _portable_model_name(v).rsplit("/", 1)[-1].casefold() == basename]
    if len(basename_matches) == 1:
        resolved = basename_matches[0]
        log.info(f"[ComfyUI] Resolved {label} by basename: '{selected}' -> '{resolved}'")
        return resolved

    preview = ", ".join(choices[:12])
    message = (
        f"The selected {label} '{selected}' is not available in ComfyUI for "
        f"{node_type}.{input_name}. Available values: {preview}"
    )
    if len(basename_matches) > 1:
        message += " (Several files share the same basename; select the exact subfolder entry.)"
    if strict:
        raise RuntimeError(message)
    log.warning("[ComfyUI] " + message)
    return selected

def comfy_list_loras(settings):
    """Interroge ComfyUI via /object_info/LoraLoader pour obtenir la liste exacte
    des noms de LoRA qu'il connaît (chemins relatifs depuis models/loras/).
    Retourne une liste de strings, ou [] si ComfyUI est inaccessible."""
    base = _comfy_base(settings)
    try:
        with urllib.request.urlopen(base + "/object_info/LoraLoader", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Structure : {"LoraLoader": {"input": {"required": {"lora_name": [["list","of","files"], ...]}}}}
        lora_name_spec = (data.get("LoraLoader", {})
                              .get("input", {})
                              .get("required", {})
                              .get("lora_name", []))
        if lora_name_spec and isinstance(lora_name_spec[0], list):
            return lora_name_spec[0]
        return []
    except Exception as e:
        log.warning(f"[LoRA] Impossible d'interroger ComfyUI /object_info/LoraLoader : {e}")
        return []


def _resolve_lora_name(requested_name, known_loras):
    """Resolve a catalog/Windows path to the exact LoRA value accepted by ComfyUI.

    Exact normalized paths win. A basename fallback is accepted only when it is unique,
    preventing the wrong LoRA from being selected when two subfolders contain the same file.
    """
    if not known_loras or not requested_name:
        return None

    def normalized(value):
        value = (value or "").strip().replace("\\", "/").lstrip("./")
        low = value.casefold()
        for marker in ("models/loras/", "loras/"):
            idx = low.find(marker)
            if idx >= 0:
                value = value[idx + len(marker):]
                break
        return value

    requested_norm = normalized(requested_name)
    exact = {normalized(name).casefold(): name for name in known_loras}
    if requested_norm.casefold() in exact:
        return exact[requested_norm.casefold()]

    basename = requested_norm.rsplit("/", 1)[-1].casefold()
    matches = [name for name in known_loras
               if normalized(name).rsplit("/", 1)[-1].casefold() == basename]
    return matches[0] if len(matches) == 1 else None


def _lora_slot_bypass(wf, lora_node_id, lora_decl):
    """Retire le node slot LoRA du workflow et recâble ses consommateurs vers les sources
    originales (UNet et CLIP). Appelé quand aucune LoRA n'est active.

    Le node slot a la forme :
        inputs = { "model": [unet_id, 0], "clip": [clip_id, 0], ... }
        outputs : slot 0 = model passthrough, slot 1 = clip passthrough

    Les consommateurs qui pointaient vers [slot_id, 0] reprennent [unet_id, 0].
    Les consommateurs qui pointaient vers [slot_id, 1] reprennent [clip_id, 0].
    Puis le node slot est supprimé du workflow.
    """
    nid = str(lora_node_id)
    if nid not in wf:
        return wf

    slot_inp  = wf[nid].get("inputs", {})
    orig_model = slot_inp.get("model")   # ex: ["212", 0]
    orig_clip  = slot_inp.get("clip")    # ex: ["211", 0]

    for node_id, node in list(wf.items()):
        if node_id == nid:
            continue
        inp = node.get("inputs", {})
        for key, val in list(inp.items()):
            if not isinstance(val, list) or len(val) != 2:
                continue
            if str(val[0]) == nid:
                if val[1] == 0 and orig_model is not None:
                    inp[key] = list(orig_model)   # recâble vers UNet
                elif val[1] == 1 and orig_clip is not None:
                    inp[key] = list(orig_clip)    # recâble vers CLIP

    del wf[nid]
    return wf


def _inject_krea2_sampler(wf, settings):
    """Inject Krea 2 sampler values with safe Turbo/Raw profiles.

    ``auto`` keeps custom values for unknown derivatives, uses 8/1 for names containing
    Turbo/distilled, and 52/3.5 for RAW checkpoints. This prevents selecting RAW while
    silently keeping the Turbo sampler.
    """
    profile = (settings.get("krea2_sampler_profile") or "auto").strip().lower()
    model_name = (settings.get("krea2_unet") or "").strip().lower()

    try:
        custom_steps = int(float(settings.get("krea2_steps", "8") or "8"))
    except (TypeError, ValueError):
        custom_steps = 8
    try:
        custom_cfg = float(settings.get("krea2_cfg", "1.0") or "1.0")
    except (TypeError, ValueError):
        custom_cfg = 1.0

    resolved_profile = profile
    if profile == "auto":
        if "raw" in model_name and "turbo" not in model_name:
            resolved_profile = "raw"
        elif "turbo" in model_name or "distill" in model_name:
            resolved_profile = "turbo"
        else:
            resolved_profile = "custom"

    if resolved_profile == "raw":
        steps, cfg = 52, 3.5
    elif resolved_profile == "turbo":
        steps, cfg = 8, 1.0
    else:
        steps, cfg = custom_steps, custom_cfg

    steps = max(1, min(steps, 100))
    cfg = max(0.0, min(cfg, 30.0))
    for node in wf.values():
        if node.get("class_type") == "KSampler":
            inp = node.get("inputs", {})
            if "steps" in inp and not isinstance(inp["steps"], list):
                inp["steps"] = steps
            if "cfg" in inp and not isinstance(inp["cfg"], list):
                inp["cfg"] = cfg
    return wf


def _inject_krea2_loras(wf, settings, wf_name=""):
    """Inject Krea 2 LoRAs into three explicit optional slots.

      301 = Character LoRA 1 / main chat character
      302 = Character LoRA 2 / user persona or secondary subject
      303 = Utility LoRA / style, rendering, effect

    Every slot is optional. Empty values or "none" are bypassed by removing the
    corresponding node and rewiring its consumers; empty LoRA names are never sent
    to ComfyUI.
    """
    def _fnum(key, default):
        try:
            return float(settings.get(key, default) or default)
        except (TypeError, ValueError):
            return float(default)

    def _lora_value(key):
        raw = (settings.get(key) or "").strip()
        return "" if raw.lower() in ("", "none", "null", "off", "disabled") else raw

    slots = (
        (model_manifests.LORA_SLOT_PRIMARY,   _lora_value("krea2_char_lora"),
         max(0.0, min(_fnum("krea2_char_lora_strength", 1.0), 2.0)), "character 1"),
        (model_manifests.LORA_SLOT_SECONDARY, _lora_value("krea2_char2_lora"),
         max(0.0, min(_fnum("krea2_char2_lora_strength", 1.0), 2.0)), "character 2"),
        (getattr(model_manifests, "LORA_SLOT_TERTIARY", "303"), _lora_value("krea2_util_lora"),
         max(0.0, min(_fnum("krea2_util_lora_strength", 0.8), 2.0)), "utility"),
    )

    known_loras = comfy_list_loras(settings) if any(name for _, name, _, _ in slots) else []

    def _resolve(name, label):
        if not name:
            return ""
        resolved = _resolve_lora_name(name, known_loras) if known_loras else name
        if known_loras and resolved is None:
            available = ", ".join(known_loras[:12])
            raise RuntimeError(
                f"Krea 2 {label} LoRA '{name}' is not available in ComfyUI. "
                f"Select an exact LoRA entry from: {available}"
            )
        if resolved != name:
            log.info(f"[Krea2/LoRA] {label} name resolved: '{name}' → '{resolved}'")
        return resolved

    for node_id, lora_name, strength, label in slots:
        lora_name = _resolve(lora_name, label)
        if lora_name:
            if node_id not in wf:
                log.warning(f"[Krea2/LoRA] Slot {label} ({node_id}) absent de '{wf_name}'")
                continue
            inp = wf[node_id].get("inputs", {})
            inp["lora_name"]      = lora_name
            inp["strength_model"] = strength
            if "strength_clip" in inp:
                inp["strength_clip"] = strength
            log.info(f"[Krea2/LoRA] slot {label} ({node_id}) ← '{lora_name}' str={strength}")
        else:
            if node_id in wf:
                log.info(f"[Krea2/LoRA] Slot {label} ({node_id}) none — bypass dans '{wf_name}'")
                wf = _lora_slot_bypass(wf, node_id, None)
    return wf


def _inject_loras_via_slot(wf, prompt, settings, family_id, wf_name=""):
    """Injecte jusqu'à 2 LoRA via les slots natifs déclarés dans le manifest.

    Slot principal (301) : première LoRA active.
    Slot secondaire (302) : deuxième LoRA active (si disponible dans le manifest).
    Maximum strict : 2 LoRA. Au-delà, les suivantes sont ignorées avec un log warning.

    Bypass propre pour chaque slot vide : le node est retiré du graphe et ses
    consommateurs recâblés vers la source précédente. ComfyUI ne voit jamais
    un LoraLoader avec lora_name vide.
    """
    # Charger la pile LoRA
    try:
        loras_raw = settings.get("loras")
        if isinstance(loras_raw, str):
            loras_raw = json.loads(loras_raw or "[]")
        if not isinstance(loras_raw, list):
            loras_raw = []
    except Exception:
        loras_raw = []

    # Manifest
    manifest = model_manifests.get_workflow_manifest(wf_name) if wf_name else None
    slots    = model_manifests.get_lora_slots_from_manifest(manifest)
    max_loras = model_manifests.get_max_active_loras(manifest)

    if not slots:
        if loras_raw:
            log.info(f"[LoRA] '{wf_name}' has no declared slot — generation without LoRA")
        return wf

    # Construire les LoRA actives (trigger/always + famille + max 2)
    prompt_l = (prompt or "").lower()
    active = []
    for lo in loras_raw:
        f = (lo.get("file") or "").strip()
        if not f:
            continue
        trig   = (lo.get("trigger") or "").strip().lower()
        always = bool(lo.get("always"))
        lo_fam = (lo.get("family") or "").strip()
        if not (always or (trig and trig in prompt_l)):
            continue
        if lo_fam and lo_fam != family_id:
            log.warning(f"[LoRA] '{f}' ignored: family '{lo_fam}' ≠ '{family_id}'")
            continue
        try:    strength = float(lo.get("strength", 0.8))
        except: strength = 0.8
        try:    clip_strength = float(lo.get("clip_strength") or 1.0)
        except: clip_strength = 1.0
        active.append({"file": f, "strength": strength, "clip_strength": clip_strength})

    # Limite stricte : 2 LoRA maximum
    if len(active) > max_loras:
        log.warning(f"[LoRA] {len(active)} LoRA actives — limite {max_loras} : "
                    f"seules les {max_loras} first ones are injected.")
        active = active[:max_loras]

    # Confirm les noms contre ComfyUI (une seule requête pour les deux)
    known_loras = comfy_list_loras(settings)
    validated = []
    for lo in active:
        resolved = _resolve_lora_name(lo["file"], known_loras) if known_loras else lo["file"]
        if known_loras and resolved is None:
            log.error(f"[LoRA] '{lo['file']}' not found in ComfyUI — ignored.")
            continue
        if resolved != lo["file"]:
            log.info(f"[LoRA] Name resolved: '{lo['file']}' → '{resolved}'")
        validated.append({**lo, "file": resolved})

    # Traiter chaque slot dans l'ordre (primary, secondary)
    for i, slot_decl in enumerate(slots):
        node_id   = str(slot_decl["node_id"])
        name_key  = slot_decl.get("lora_name_input",      "lora_name")
        model_key = slot_decl.get("model_strength_input", "strength_model")
        clip_key  = slot_decl.get("clip_strength_input",  "strength_clip")

        if i < len(validated):
            # Slot occupé — injecter
            if node_id not in wf:
                log.warning(f"[LoRA] Slot '{slot_decl['slot']}' node {node_id} absent de '{wf_name}'")
                continue
            lo = validated[i]
            inp = wf[node_id].get("inputs", {})
            inp[name_key]  = lo["file"]
            inp[model_key] = lo["strength"]
            if clip_key and clip_key in inp:
                inp[clip_key] = lo["clip_strength"]
            log.info(f"[LoRA] slot {slot_decl['slot']} ({node_id}) ← '{lo['file']}' "
                     f"str={lo['strength']} clip={lo['clip_strength']}")
        else:
            # Slot vide — bypass propre
            if node_id in wf:
                log.info(f"[LoRA] Slot {slot_decl['slot']} ({node_id}) vide — bypass dans '{wf_name}'")
                wf = _lora_slot_bypass(wf, node_id, slot_decl)

    return wf


def _inject_loras(wf, prompt, settings):
    """ARCHIVÉ — ancienne injection dynamique (créait des nodes 9000+, recâblait la topologie).
    Conservée pour référence uniquement. Jamais appelée depuis v15.
    Utilisait _inject_loras_via_slot() à la place."""
    return wf  # désactivée
    seed_val = fixed if fixed is not None else random.randint(0, 2_147_483_646)
    for node in workflow.values():
        inputs = node.get("inputs", {})
        for key in ("seed", "noise_seed"):
            if key in inputs and not isinstance(inputs[key], list):
                inputs[key] = seed_val
    return workflow, seed_val


def comfy_upload_image(image_path, settings):
    boundary = "----companion" + uuid.uuid4().hex
    fname = os.path.basename(image_path)
    with open(image_path, "rb") as f:
        file_bytes = f.read()
    body = b""
    body += ("--" + boundary + "\r\n").encode()
    body += (f'Content-Disposition: form-data; name="image"; filename="{fname}"\r\n').encode()
    body += b"Content-Type: image/png\r\n\r\n" + file_bytes + b"\r\n"
    body += ("--" + boundary + "\r\n").encode()
    body += b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
    body += ("--" + boundary + "--\r\n").encode()
    url = _comfy_base(settings) + "/upload/image"
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out.get("name", fname)


def comfy_queue_and_fetch(workflow, settings, timeout=600):
    base = _comfy_base(settings)
    client_id = uuid.uuid4().hex
    started = time.time()
    _set_comfy_generation_state(
        state="active", stage="submitting", prompt_id=None, started=started, finished=0.0,
        error=None, queue_running=0, queue_pending=0, message="Sending workflow to ComfyUI",
    )
    try:
        payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8")
        req = urllib.request.Request(base + "/prompt", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                out = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:800]
            raise RuntimeError("ComfyUI rejected the workflow, often because of a wrong model file "
                               "name or a missing node. Details: " + detail)
        prompt_id = out["prompt_id"]
        _set_comfy_generation_state(
            state="active", stage="queued", prompt_id=prompt_id,
            message="Workflow accepted; waiting in ComfyUI queue",
        )

        deadline = time.time() + timeout
        history = None
        while time.time() < deadline:
            try:
                # Queue polling provides useful live state without pretending to know a percent.
                with urllib.request.urlopen(base + "/queue", timeout=5) as resp:
                    queue = json.loads(resp.read().decode("utf-8"))
                running_items = queue.get("queue_running", [])
                pending_items = queue.get("queue_pending", [])
                serialized_running = json.dumps(running_items, ensure_ascii=False)
                serialized_pending = json.dumps(pending_items, ensure_ascii=False)
                if prompt_id in serialized_running:
                    stage, message = "generating", "ComfyUI is generating the image"
                elif prompt_id in serialized_pending:
                    stage, message = "queued", "Workflow is waiting in the ComfyUI queue"
                else:
                    stage, message = "processing", "ComfyUI is finalizing the workflow"
                _set_comfy_generation_state(
                    state="active", stage=stage, prompt_id=prompt_id,
                    queue_running=len(running_items), queue_pending=len(pending_items), message=message,
                )
            except Exception:
                pass

            try:
                with urllib.request.urlopen(base + "/history/" + prompt_id, timeout=30) as resp:
                    h = json.loads(resp.read().decode("utf-8"))
                if prompt_id in h and h[prompt_id].get("outputs"):
                    history = h[prompt_id]
                    break
            except urllib.error.URLError:
                pass
            time.sleep(1.0)
        if not history:
            raise RuntimeError("ComfyUI: timeout exceeded, no image produced (see the persistent logs/comfyui.log file).")

        _set_comfy_generation_state(
            state="active", stage="downloading", prompt_id=prompt_id,
            message="Image generated; downloading result from ComfyUI",
        )
        for node_out in history["outputs"].values():
            for img in node_out.get("images", []):
                qs = urllib.parse.urlencode({
                    "filename": img["filename"],
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                })
                with urllib.request.urlopen(base + "/view?" + qs, timeout=60) as resp:
                    data = resp.read()
                local = _new_name() + "_" + img["filename"]
                dest_path = os.path.join(IMG_DIR, local)
                try:
                    with open(dest_path, "wb") as f:
                        f.write(data)
                except OSError as e:
                    raise RuntimeError(
                        f"ComfyUI: image generated but unable to copy it to {dest_path}: {e}"
                    )
                if not os.path.isfile(dest_path):
                    raise RuntimeError(
                        f"ComfyUI: copy to {dest_path} seemed to succeed but the file is missing."
                    )
                log.info("[comfy] Image saved: %s", dest_path)
                _set_comfy_generation_state(
                    state="complete", stage="complete", prompt_id=prompt_id,
                    finished=time.time(), error=None, message="Image generation complete",
                )
                return local
        raise RuntimeError("ComfyUI: response received but no image was found.")
    except Exception as exc:
        _set_comfy_generation_state(
            state="error", stage="error", finished=time.time(), error=str(exc), message=str(exc),
        )
        raise


def generate_t2i(prompt, settings, negative=None, seed=None, workflow=None, family=None):
    with lmstudio_vram.vram_lock_for_image():
        _unload_lmstudio_before_image(settings)
        with _LOCK:
            if settings.get("vram_mode", "swap") == "swap":
                free_llm()
            comfy_ensure(settings)
            fam = (family or settings.get("image_family") or "flux2_klein").strip()
            # Workflow explicite prioritaire (Studio, preview LoRA, etc.)
            # Sinon : sélectionner le bon variant selon flux2_loader_mode
            if workflow:
                wf_name = workflow
            elif fam == "flux2_klein":
                wf_name = _flux2_workflow(settings.get("t2i_workflow", "t2i.json"), settings)
            elif fam == "krea2":
                # Krea 2 : UN SEUL workflow unifié pour tous les usages T2I
                wf_name = model_manifests.KREA2_WORKFLOW
            else:
                wf_name = settings.get("t2i_workflow", "t2i.json")
            if fam == "krea2" and not os.path.exists(os.path.join(WF_DIR, wf_name)):
                raise RuntimeError(
                    f"Krea 2 workflow not found ({wf_name}). "
                    "Make sure workflows/krea2/krea2_unified.json exists.")
            raw = open(os.path.join(WF_DIR, wf_name), "r", encoding="utf-8").read()
            wf = _comfy_inject(raw, prompt, settings, negative=negative, family=fam,
                               wf_name=os.path.basename(wf_name))
            wf, used_seed = _comfy_randomize_seeds(wf, fixed=seed)
            img = comfy_queue_and_fetch(wf, settings)
            return img, used_seed


def generate_i2i(prompt, init_image_filename, settings, negative=None, seed=None, workflow=None, family=None):
    with lmstudio_vram.vram_lock_for_image():
        _unload_lmstudio_before_image(settings)
        with _LOCK:
            if settings.get("vram_mode", "swap") == "swap":
                free_llm()
            comfy_ensure(settings)
            fam = (family or settings.get("image_family") or "flux2_klein").strip()
            if fam == "krea2":
                # Global Krea mode: every image feature uses the single unified T2I workflow.
                # The source image is intentionally not injected; identity is provided by the
                # character LoRA + full physical description in the prompt.
                log.info("[Krea2] I2I feature routed to unified T2I workflow (reference image ignored).")
                wf_name = model_manifests.KREA2_WORKFLOW
                raw = open(os.path.join(WF_DIR, wf_name), "r", encoding="utf-8").read()
                wf = _comfy_inject(raw, prompt, settings, negative=negative, family="krea2",
                                   wf_name=os.path.basename(wf_name))
                wf, used_seed = _comfy_randomize_seeds(wf, fixed=seed)
                return comfy_queue_and_fetch(wf, settings), used_seed
            init_path = os.path.join(IMG_DIR, init_image_filename)
            uploaded = comfy_upload_image(init_path, settings)
            if workflow:
                wf_name = workflow
            elif fam == "flux2_klein":
                wf_name = _flux2_workflow(settings.get("i2i_workflow", "i2i.json"), settings)
            else:
                wf_name = settings.get("i2i_workflow", "i2i.json")
            raw = open(os.path.join(WF_DIR, wf_name), "r", encoding="utf-8").read()
            wf = _comfy_inject(raw, prompt, settings, negative=negative, image_name=uploaded,
                               family=fam, wf_name=os.path.basename(wf_name))
            wf, used_seed = _comfy_randomize_seeds(wf, fixed=seed)
            img = comfy_queue_and_fetch(wf, settings)
            return img, used_seed


def generate_group(prompt, image_list, settings, negative=None, seed=None, workflow=None,
                   background=None, family=None):
    """Illustration multi-references. Workflows : duo (2 refs), trio (3 refs + fond optionnel),
    group4 (4 refs). Corrige FileNotFoundError : verifie chaque fichier avant upload."""
    import re as _re
    with lmstudio_vram.vram_lock_for_image():
        _unload_lmstudio_before_image(settings)
        with _LOCK:
            if settings.get("vram_mode", "swap") == "swap":
                free_llm()
            comfy_ensure(settings)
            fam = (family or settings.get("image_family") or "flux2_klein").strip()
            if fam == "krea2":
                # Krea 2 uses the unified descriptive T2I workflow globally. Group prompts
                # describe every subject explicitly, so source avatars are not required.
                log.info("[Krea2] Group feature routed to unified descriptive T2I workflow.")
                wf_name = model_manifests.KREA2_WORKFLOW
                raw = open(os.path.join(WF_DIR, wf_name), "r", encoding="utf-8").read()
                wf = _comfy_inject(raw, prompt, settings, negative=negative, family="krea2",
                                   wf_name=os.path.basename(wf_name))
                wf, used_seed = _comfy_randomize_seeds(wf, fixed=seed)
                return comfy_queue_and_fetch(wf, settings), used_seed

            if not image_list:
                raise RuntimeError("No reference image was provided for this Flux scene.")

            # Filter reference images that physically exist for Flux workflows.
            def img_exists(name):
                if not name:
                    return False
                p = os.path.join(IMG_DIR, os.path.basename(name))
                return os.path.exists(p)

            valid = [(img, nm) for img, nm in zip(image_list,
                     [str(i) for i in range(len(image_list))]) if img_exists(img)]
            if not valid:
                raise RuntimeError("No image file found in data/images/. "
                                   "Make sure avatars have been generated.")
            image_list = [v[0] for v in valid]

            # Choose the Flux workflow.
            if workflow is None:
                n = len(image_list)
                if n <= 2:
                    base_wf = settings.get("duo_workflow", "duo.json")
                elif n == 3:
                    wf_dir = os.path.join(os.path.dirname(__file__), "workflows")
                    base_wf = "trio.json" if os.path.exists(os.path.join(wf_dir, "trio.json")) \
                        else settings.get("group_workflow", "group4.json")
                else:
                    base_wf = settings.get("group_workflow", "group4.json")
                # Appliquer le bon variant selon flux2_loader_mode
                workflow = _flux2_workflow(base_wf, settings) if fam == "flux2_klein" else base_wf
            elif fam == "flux2_klein" and not workflow.endswith("_st.json"):
                # workflow explicite fourni mais pas encore suffixé → appliquer le mode
                workflow = _flux2_workflow(workflow, settings)

            raw = open(os.path.join(WF_DIR, workflow), "r", encoding="utf-8").read()

            # Jetons image numerotes
            tokens = sorted(set(_re.findall(r"%IMAGE(\d+)%", raw)), key=lambda x: int(x))
            if not tokens:
                # workflow a un seul jeton %IMAGE% -- appel reentrant : generate_i2i tentera
                # de reacquerir LMSTUDIO_VRAM_LOCK, ce qui est sans danger car RLock (le meme
                # thread peut le reacquerir), et evite de redecharger LM Studio inutilement
                # puisque c'est deja fait dans ce meme cycle.
                return generate_i2i(prompt, os.path.basename(image_list[0]), settings, negative, seed)

            uploaded_cache = {}

            def upload_safe(fname):
                """Upload avec chemin absolu verifie."""
                bname = os.path.basename(fname)
                p = os.path.join(IMG_DIR, bname)
                if not os.path.exists(p):
                    raise RuntimeError(f"Image not found: {bname}")
                if fname not in uploaded_cache:
                    uploaded_cache[fname] = comfy_upload_image(p, settings)
                return uploaded_cache[fname]

            txt = raw
            txt = txt.replace(settings.get("prompt_token", "%PROMPT%"), _json_escape(prompt))
            neg = negative if negative is not None else settings.get("default_negative", "")
            txt = txt.replace(settings.get("negative_token", "%NEGATIVE%"), _json_escape(neg))

            for n in tokens:
                idx = int(n) - 1
                src = image_list[idx] if idx < len(image_list) else image_list[-1]
                txt = txt.replace("%IMAGE" + n + "%", _json_escape(upload_safe(src)))

            # Jeton fond (%BACKGROUND%) : fond fourni, sinon image[-1]
            if "%BACKGROUND%" in txt:
                bg_src = background if (background and img_exists(background)) else image_list[-1]
                txt = txt.replace("%BACKGROUND%", _json_escape(upload_safe(bg_src)))

            wf = json.loads(txt)
            _inject_models_for_family(wf, settings, fam)
            wf = _inject_loras_via_slot(wf, prompt, settings, fam,
                                        wf_name=os.path.basename(workflow))
            wf, used_seed = _comfy_randomize_seeds(wf, fixed=seed)
            img = comfy_queue_and_fetch(wf, settings)
            return img, used_seed
