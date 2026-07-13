# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""Remote provider helpers for OpenAI-compatible APIs and Runpod.

AmiorAI remains only a frontend. Every request uses credentials supplied by the user,
and Runpod billing stays between Runpod and that user.
"""
from __future__ import annotations

import base64
import contextlib
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

log = logging.getLogger("AmiorAI.remote")
RUNPOD_REST_BASE = "https://rest.runpod.io/v1"
RUNPOD_SERVERLESS_BASE = "https://api.runpod.ai/v2"


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            text = exc.read().decode("utf-8", "replace").strip()
            if text:
                try:
                    payload = json.loads(text)
                    error = payload.get("error", payload) if isinstance(payload, dict) else payload
                    if isinstance(error, dict):
                        return str(error.get("message") or error.get("detail") or error)
                    return str(error)
                except Exception:
                    return text[:1200]
        except Exception:
            pass
    return str(exc)


def request_json(url: str, *, method: str = "GET", payload: Any = None,
                 api_key: str = "", timeout: float = 30,
                 extra_headers: dict[str, str] | None = None) -> Any:
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    if extra_headers:
        headers.update(extra_headers)
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            if not raw:
                return {}
            text = raw.decode("utf-8", "replace")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}: {_error_detail(exc)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to reach {url}: {exc.reason or exc}") from exc


def normalize_openai_base(value: str | None, default: str = "") -> str:
    base = (value or default or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/api/v1"):
        base = base[:-len("/api/v1")]
    if base.endswith("/v1"):
        return base
    return base + "/v1"


def openai_models(base_url: str, api_key: str = "", timeout: float = 15) -> list[str]:
    base = normalize_openai_base(base_url)
    if not base:
        raise RuntimeError("The OpenAI-compatible server URL is empty.")
    payload = request_json(base + "/models", api_key=api_key, timeout=timeout)
    items = (payload.get("data") or payload.get("models") or []) if isinstance(payload, dict) else []
    result: list[str] = []
    for item in items if isinstance(items, list) else []:
        model_id = (item.get("id") or item.get("name") or item.get("key")) if isinstance(item, dict) else str(item)
        if model_id and str(model_id) not in result:
            result.append(str(model_id))
    return result


def openai_chat(base_url: str, api_key: str, model: str, messages: list[dict],
                max_tokens: int, temperature: float, stop=None, timeout: float = 600) -> str:
    base = normalize_openai_base(base_url)
    if not base:
        raise RuntimeError("The OpenAI-compatible server URL is empty.")
    selected = str(model or "").strip()
    if not selected:
        models = openai_models(base, api_key, timeout=min(timeout, 20))
        if len(models) == 1:
            selected = models[0]
        elif not models:
            raise RuntimeError("The remote server exposes no model through /v1/models.")
        else:
            raise RuntimeError("Several remote models are available. Select one in AmiorAI Settings.")
    body = {
        "model": selected, "messages": messages, "max_tokens": int(max_tokens),
        "temperature": float(temperature), "stream": False,
    }
    if stop:
        body["stop"] = stop
    payload = request_json(base + "/chat/completions", method="POST", payload=body,
                           api_key=api_key, timeout=timeout)
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise RuntimeError(f"The remote LLM returned no choices: {payload}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") if isinstance(part, dict) else str(part)
                          for part in content)
    if not str(content or "").strip():
        content = choices[0].get("text")
    if not str(content or "").strip():
        raise RuntimeError("The remote LLM returned no usable text.")
    return str(content).strip()


def runpod_serverless_openai_base(endpoint_id: str) -> str:
    endpoint = str(endpoint_id or "").strip()
    return f"{RUNPOD_SERVERLESS_BASE}/{urllib.parse.quote(endpoint)}/openai/v1" if endpoint else ""


def _extract_image_value(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        for item in output:
            try:
                return _extract_image_value(item)
            except RuntimeError:
                continue
    if isinstance(output, dict):
        for key in ("message", "data", "image", "url"):
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
        images = output.get("images")
        if isinstance(images, list):
            for item in images:
                try:
                    return _extract_image_value(item)
                except RuntimeError:
                    continue
        for value in output.values():
            if isinstance(value, (dict, list)):
                try:
                    return _extract_image_value(value)
                except RuntimeError:
                    continue
    raise RuntimeError("The Runpod worker completed without an image in its output.")


def decode_remote_image(value: str, timeout: float = 120) -> bytes:
    text = str(value or "").strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    if text.startswith(("http://", "https://")):
        with urllib.request.urlopen(text, timeout=timeout) as response:
            return response.read()
    try:
        return base64.b64decode(text, validate=False)
    except Exception as exc:
        raise RuntimeError("The remote image result is neither a URL nor valid base64 data.") from exc


def runpod_serverless_image(endpoint_id: str, api_key: str, workflow: dict,
                            images: list[dict] | None = None, timeout: float = 900,
                            progress: Callable[[str, str], None] | None = None) -> tuple[bytes, str]:
    endpoint = str(endpoint_id or "").strip()
    if not endpoint:
        raise RuntimeError("Runpod image Endpoint ID is missing.")
    if not api_key:
        raise RuntimeError("Runpod API key is not configured.")
    base = f"{RUNPOD_SERVERLESS_BASE}/{urllib.parse.quote(endpoint)}"
    job_payload = {
        "input": {"workflow": workflow, "images": images or []},
        "policy": {"executionTimeout": int(max(30, timeout) * 1000),
                   "ttl": int(max(60, timeout + 300) * 1000)},
    }
    if progress:
        progress("submitting", "Sending workflow to Runpod Serverless")
    submitted = request_json(base + "/run", method="POST", payload=job_payload,
                             api_key=api_key, timeout=60)
    job_id = str((submitted or {}).get("id") or "")
    if not job_id:
        raise RuntimeError(f"Runpod did not return a job ID: {submitted}")
    deadline = time.time() + timeout
    last_status = "IN_QUEUE"
    while time.time() < deadline:
        status = request_json(base + "/status/" + urllib.parse.quote(job_id),
                              api_key=api_key, timeout=60)
        last_status = str((status or {}).get("status") or "UNKNOWN").upper()
        if progress:
            progress("queued" if last_status in ("IN_QUEUE", "QUEUED") else "generating",
                     f"Runpod job: {last_status}")
        if last_status == "COMPLETED":
            return decode_remote_image(_extract_image_value(status.get("output"))), job_id
        if last_status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise RuntimeError(f"Runpod image job {last_status}: {status.get('error') or status.get('output') or status}")
        time.sleep(1.0)
    try:
        request_json(base + "/cancel/" + urllib.parse.quote(job_id), method="POST", payload={},
                     api_key=api_key, timeout=20)
    except Exception:
        pass
    raise RuntimeError(f"Runpod image job timed out after {timeout:g} seconds (last status: {last_status}).")


def runpod_pod_info(pod_id: str, api_key: str) -> dict:
    pod = str(pod_id or "").strip()
    if not pod:
        raise RuntimeError("Runpod Pod ID is missing.")
    if not api_key:
        raise RuntimeError("Runpod API key is not configured.")
    return request_json(f"{RUNPOD_REST_BASE}/pods/{urllib.parse.quote(pod)}", api_key=api_key, timeout=30)


def runpod_pod_status(info: dict | None) -> str:
    data = info or {}
    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    value = (data.get("desiredStatus") or data.get("status") or data.get("podStatus")
             or runtime.get("status") or runtime.get("desiredStatus") or "")
    return str(value).strip().upper()


def runpod_pod_action(pod_id: str, api_key: str, action: str) -> dict:
    if action not in ("start", "stop", "restart"):
        raise ValueError("Unsupported Runpod Pod action.")
    pod = str(pod_id or "").strip()
    if not pod:
        raise RuntimeError("Runpod Pod ID is missing.")
    if not api_key:
        raise RuntimeError("Runpod API key is not configured.")
    return request_json(f"{RUNPOD_REST_BASE}/pods/{urllib.parse.quote(pod)}/{action}",
                        method="POST", payload=None, api_key=api_key, timeout=60)


def probe_url(url: str, api_key: str = "", timeout: float = 5) -> bool:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


class _PodAutoStopManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._states: dict[str, dict] = {}
        self._thread = threading.Thread(target=self._loop, name="AmiorAI-Runpod-AutoStop", daemon=True)
        self._thread.start()

    def _state(self, role: str) -> dict:
        with self._lock:
            return self._states.setdefault(role, {
                "active_jobs": 0, "last_activity": 0.0, "pod_id": "", "api_key": "",
                "idle_seconds": 900, "auto_stop": True, "last_action": "idle",
                "last_error": None, "starting": False, "stopping": False,
            })

    def configure(self, role: str, pod_id: str, api_key: str, idle_seconds: int, auto_stop: bool):
        with self._lock:
            self._state(role).update(pod_id=str(pod_id or "").strip(), api_key=api_key or "",
                                     idle_seconds=max(60, int(idle_seconds or 900)), auto_stop=bool(auto_stop))

    def begin(self, role: str):
        with self._lock:
            state = self._state(role); state["active_jobs"] += 1; state["last_activity"] = time.time()

    def end(self, role: str):
        with self._lock:
            state = self._state(role)
            state["active_jobs"] = max(0, int(state.get("active_jobs", 0)) - 1)
            state["last_activity"] = time.time(); state["last_action"] = "idle countdown"

    def set_action(self, role: str, action: str, error: str | None = None):
        with self._lock:
            state = self._state(role)
            state["last_action"] = action; state["last_error"] = error
            state["starting"] = action == "starting"; state["stopping"] = action == "stopping"
            if action.startswith("stopped"):
                state["active_jobs"] = 0; state["last_activity"] = 0.0

    def status(self, role: str) -> dict:
        with self._lock:
            state = dict(self._state(role))
        remaining = None
        if state.get("last_activity") and state.get("auto_stop") and not state.get("active_jobs"):
            remaining = max(0, int(state.get("idle_seconds", 900) - (time.time() - state["last_activity"])))
        state.pop("api_key", None); state["idle_remaining_seconds"] = remaining
        return state

    def stop_configured_pods(self, reason: str = "application shutdown") -> list[dict]:
        with self._lock:
            snapshot = {role: dict(state) for role, state in self._states.items()}
        results = []
        for role, state in snapshot.items():
            if not state.get("auto_stop") or not state.get("pod_id") or not state.get("api_key"):
                continue
            try:
                pod_state = runpod_pod_status(runpod_pod_info(state["pod_id"], state["api_key"]))
                if pod_state in ("RUNNING", "READY"):
                    runpod_pod_action(state["pod_id"], state["api_key"], "stop")
                    self.set_action(role, "stopped on shutdown")
                    log.info("[Runpod] %s Pod stopped on %s", role, reason)
                    results.append({"role": role, "stopped": True})
                else:
                    self.set_action(role, "stopped")
                    results.append({"role": role, "stopped": False, "state": pod_state})
            except Exception as exc:
                self.set_action(role, "shutdown stop failed", str(exc))
                log.warning("[Runpod] stop on %s failed for %s: %s", reason, role, exc)
                results.append({"role": role, "stopped": False, "error": str(exc)})
        return results

    def check_idle_once(self, now: float | None = None):
        now = time.time() if now is None else float(now)
        with self._lock:
            snapshot = {role: dict(state) for role, state in self._states.items()}
        for role, state in snapshot.items():
            if not state.get("auto_stop") or state.get("active_jobs") or state.get("stopping"):
                continue
            if not state.get("pod_id") or not state.get("api_key") or not state.get("last_activity"):
                continue
            if now - state["last_activity"] < state.get("idle_seconds", 900):
                continue
            self.set_action(role, "stopping")
            try:
                if runpod_pod_status(runpod_pod_info(state["pod_id"], state["api_key"])) in ("RUNNING", "READY"):
                    runpod_pod_action(state["pod_id"], state["api_key"], "stop")
                    log.info("[Runpod] %s Pod stopped after inactivity", role)
                self.set_action(role, "stopped after inactivity")
            except Exception as exc:
                self.set_action(role, "auto-stop failed", str(exc))
                log.warning("[Runpod] automatic stop failed for %s: %s", role, exc)

    def _loop(self):
        while True:
            time.sleep(5); self.check_idle_once()


POD_MANAGER = _PodAutoStopManager()


def ensure_runpod_pod(role: str, pod_id: str, api_key: str, health_url: str,
                      health_api_key: str = "", timeout: float = 900,
                      idle_seconds: int = 900, auto_stop: bool = True) -> dict:
    POD_MANAGER.configure(role, pod_id, api_key, idle_seconds, auto_stop)
    if not str(health_url or "").strip():
        raise RuntimeError(f"Runpod {role} Pod API URL is missing.")
    info = runpod_pod_info(pod_id, api_key)
    if runpod_pod_status(info) not in ("RUNNING", "READY"):
        POD_MANAGER.set_action(role, "starting")
        runpod_pod_action(pod_id, api_key, "start")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if probe_url(health_url, health_api_key, timeout=5):
            POD_MANAGER.set_action(role, "ready")
            return runpod_pod_info(pod_id, api_key)
        time.sleep(2)
    POD_MANAGER.set_action(role, "start timeout", f"API not ready at {health_url}")
    raise RuntimeError(f"Runpod {role} Pod started but its API did not become ready at {health_url} within {timeout:g} seconds.")


@contextlib.contextmanager
def runpod_pod_job(role: str, pod_id: str, api_key: str, health_url: str,
                   health_api_key: str = "", timeout: float = 900,
                   idle_seconds: int = 900, auto_stop: bool = True):
    ensure_runpod_pod(role, pod_id, api_key, health_url, health_api_key,
                      timeout, idle_seconds, auto_stop)
    POD_MANAGER.begin(role)
    try:
        yield
    finally:
        POD_MANAGER.end(role)
