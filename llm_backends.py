# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""Discovery helpers for local and user-owned remote text engines."""
from __future__ import annotations

import remote_runtime
import secret_store

BACKEND_LABELS = {
    "lmstudio": "LM Studio",
    "openai_compatible": "OpenAI-compatible server",
    "runpod_serverless": "Runpod Serverless vLLM",
    "runpod_pod": "Runpod Pod vLLM",
}
BACKEND_MODEL_FORMATS = {key: ("OpenAI-compatible",) for key in BACKEND_LABELS}


def list_backends():
    return [{"id": key, "label": label, "formats": BACKEND_MODEL_FORMATS[key]}
            for key, label in BACKEND_LABELS.items()]


def normalize_lmstudio_url(value: str | None) -> str:
    return remote_runtime.normalize_openai_base(value, "http://127.0.0.1:1234/v1")


def _connection(backend_id, settings):
    backend = backend_id if backend_id in BACKEND_LABELS else settings.get("llm_backend", "lmstudio")
    if backend == "lmstudio":
        return normalize_lmstudio_url(settings.get("lmstudio_url")), (settings.get("lmstudio_api_key") or ""), "lmstudio"
    if backend == "openai_compatible":
        return remote_runtime.normalize_openai_base(settings.get("llm_remote_url")), secret_store.get_secret("llm_remote_api_key"), backend
    if backend == "runpod_serverless":
        return remote_runtime.runpod_serverless_openai_base(settings.get("llm_runpod_endpoint_id")), secret_store.get_secret("runpod_api_key"), backend
    return remote_runtime.normalize_openai_base(settings.get("llm_runpod_pod_url")), secret_store.get_secret("llm_remote_api_key"), backend


def probe_backend(backend_id, settings):
    base, key, backend = _connection(backend_id, settings)
    status = {"backend": backend, "reachable": False, "url": base, "models": [],
              "active_model": None, "error": None}
    if not base:
        status["error"] = "The configured API URL or Runpod Endpoint ID is empty."
        return status
    try:
        ids = remote_runtime.openai_models(base, key, timeout=8)
        status["models"] = [{"id": model_id} for model_id in ids]
        status["reachable"] = True
        configured = ((settings.get("lmstudio_model") if backend == "lmstudio" else settings.get("llm_remote_model")) or "").strip()
        if configured in ids:
            status["active_model"] = configured
        elif len(ids) == 1:
            status["active_model"] = ids[0]
    except Exception as exc:
        status["error"] = str(exc)
    return status


def probe_lmstudio(settings):
    return probe_backend("lmstudio", settings)
