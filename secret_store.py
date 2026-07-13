# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""Secure credential storage for optional remote AI providers.

Secrets never live in the SQLite settings table and are never returned to the web UI.
Windows uses Credential Manager through ``keyring``. Linux/macOS use the available
Secret Service / Keychain backend. If no backend is available, values remain in memory
for the current AmiorAI session only.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("AmiorAI.secrets")

_SERVICE = "AmiorAI"
_ALLOWED = {
    "runpod_api_key": "runpod_api_key",
    "llm_remote_api_key": "llm_remote_api_key",
    "image_remote_api_key": "image_remote_api_key",
}
_SESSION: dict[str, str] = {}
_LOCK = threading.RLock()

try:
    import keyring  # type: ignore
    from keyring.errors import KeyringError  # type: ignore
    _KEYRING_IMPORTED = True
except Exception:  # pragma: no cover - platform dependent
    keyring = None
    KeyringError = Exception
    _KEYRING_IMPORTED = False


def _validate(name: str) -> str:
    key = str(name or "").strip()
    if key not in _ALLOWED:
        raise ValueError(f"Unsupported secret slot: {key}")
    return key


def _keyring_usable() -> bool:
    if not _KEYRING_IMPORTED:
        return False
    try:
        backend = keyring.get_keyring()
        priority = getattr(backend, "priority", 0)
        return bool(priority and priority > 0)
    except Exception:
        return False


def save_secret(name: str, value: str) -> str:
    key = _validate(name)
    secret = str(value or "").strip()
    if not secret:
        raise ValueError("The secret value is empty.")
    with _LOCK:
        if _keyring_usable():
            try:
                keyring.set_password(_SERVICE, _ALLOWED[key], secret)
                _SESSION.pop(key, None)
                return "keyring"
            except KeyringError as exc:  # pragma: no cover
                log.warning("Secure keyring write failed; using session memory: %s", exc)
        _SESSION[key] = secret
        return "session"


def get_secret(name: str) -> str:
    key = _validate(name)
    with _LOCK:
        if _keyring_usable():
            try:
                value = keyring.get_password(_SERVICE, _ALLOWED[key])
                if value:
                    return value
            except KeyringError:  # pragma: no cover
                pass
        return _SESSION.get(key, "")


def delete_secret(name: str) -> None:
    key = _validate(name)
    with _LOCK:
        _SESSION.pop(key, None)
        if _keyring_usable():
            try:
                keyring.delete_password(_SERVICE, _ALLOWED[key])
            except Exception:
                pass


def secret_status(name: str) -> dict:
    key = _validate(name)
    configured = bool(get_secret(key))
    persistent = _keyring_usable()
    return {
        "name": key,
        "configured": configured,
        "storage": "keyring" if persistent else "session",
        "persistent": persistent,
        "warning": None if persistent else (
            "No usable system keyring was detected. The key is kept only in memory "
            "and will be lost when AmiorAI closes."
        ),
    }


def all_status() -> dict:
    return {name: secret_status(name) for name in sorted(_ALLOWED)}
