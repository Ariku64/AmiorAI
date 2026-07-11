# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""LM Studio discovery helpers used by AmiorAI.

AmiorAI v38.1.3 intentionally supports one text backend only: LM Studio.
Both the conversational model and the optional utility model are exposed by
the same local LM Studio OpenAI-compatible server.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BACKEND_MODEL_FORMATS = {"lmstudio": ("managed-by-lmstudio",)}
BACKEND_LABELS = {"lmstudio": "LM Studio"}


def list_backends():
    return [{"id": "lmstudio", "label": "LM Studio", "formats": ("managed-by-lmstudio",)}]


def normalize_lmstudio_url(value: str | None) -> str:
    base = (value or "http://127.0.0.1:1234/v1").strip().rstrip("/")
    if not base:
        base = "http://127.0.0.1:1234/v1"
    if base.endswith("/api/v1"):
        base = base[: -len("/api/v1")]
    elif base.endswith("/v1"):
        return base
    return base + "/v1"


def _http_get_json(url: str, timeout: float = 4.0, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_error_detail(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", "replace").strip()
            if body:
                try:
                    parsed = json.loads(body)
                    err = parsed.get("error", parsed)
                    if isinstance(err, dict):
                        return str(err.get("message") or err.get("detail") or err)
                    return str(err)
                except Exception:
                    return body[:600]
        except Exception:
            pass
    return str(exc)


def probe_lmstudio(settings):
    """Probe LM Studio's `/v1/models` endpoint without loading or unloading a model."""
    base = normalize_lmstudio_url(settings.get("lmstudio_url"))
    api_key = (settings.get("lmstudio_api_key") or "").strip()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    status = {
        "backend": "lmstudio",
        "reachable": False,
        "url": base,
        "models": [],
        "active_model": None,
        "error": None,
    }
    try:
        data = _http_get_json(base + "/models", timeout=5, headers=headers)
        items = data.get("data", []) if isinstance(data, dict) else []
        status["models"] = [
            {
                "id": m.get("id"),
                "object": m.get("object"),
                "owned_by": m.get("owned_by"),
                "state": m.get("state"),
                "loaded_instances": m.get("loaded_instances"),
            }
            for m in items
            if isinstance(m, dict) and m.get("id")
        ]
        status["reachable"] = True
        configured = (settings.get("lmstudio_model") or "").strip()
        ids = [m["id"] for m in status["models"]]
        if configured in ids:
            status["active_model"] = configured
        elif len(ids) == 1:
            status["active_model"] = ids[0]
    except urllib.error.HTTPError as exc:
        status["error"] = (
            f"LM Studio answered HTTP {exc.code} on {base}/models: "
            f"{_http_error_detail(exc)}"
        )
    except urllib.error.URLError as exc:
        status["error"] = (
            f"LM Studio is unreachable on {base}. Start the local server in LM Studio "
            f"and verify the URL. Detail: {exc.reason or exc}"
        )
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"LM Studio probe failed: {_http_error_detail(exc)}"
    return status


def probe_backend(_backend_id, settings):
    """Compatibility wrapper: every backend request resolves to LM Studio."""
    return probe_lmstudio(settings)
