#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
"""AmiorAI v40 local TTS server.

Supported engines:
  - chatterbox: Resemble AI Chatterbox Multilingual V3 (default)
  - qwen:       Qwen3-TTS 0.6B Base voice cloning (optional)

On Windows, each engine runs in its own official embeddable Python runtime.
Linux/macOS keep separate virtual environments. See the matching installer.

Endpoints:
  GET  /health
  POST /clone_check   {speaker_wav}
  POST /tts           {text, language, speaker_wav, reference_text?, speed?,
                       exaggeration?, cfg_weight?, temperature?}
  POST /shutdown      release the TTS process and all CUDA allocations
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import html
import io
import importlib.metadata
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import traceback
import unicodedata

try:
    from flask import Flask, jsonify, request, send_file
except ImportError:
    print(
        "\n[tts_server] Flask is missing. Run the installer matching the selected engine "
        "inside the tts_server folder.\n",
        file=sys.stderr,
    )
    raise SystemExit(1)

app = Flask(__name__)
STATE = {
    "status": "loading",
    "engine": None,
    "device": None,
    "error": None,
    "model": None,
    "sample_rate": None,
    "package_version": None,
    "runtime": sys.executable,
}
_MODEL = None
_LOCK = threading.RLock()
_QWEN_PROMPTS: OrderedDict[tuple, object] = OrderedDict()
_QWEN_PROMPT_CACHE_SIZE = 8

CHATTERBOX_LANGUAGES = {
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja",
    "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
}
QWEN_LANGUAGE_NAMES = {
    "zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean",
    "de": "German", "fr": "French", "ru": "Russian", "pt": "Portuguese",
    "es": "Spanish", "it": "Italian",
}


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _select_device(torch, requested: str) -> str:
    requested = (requested or "auto").strip().lower()
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was explicitly selected but PyTorch cannot access an NVIDIA GPU.")
        return "cuda"
    if requested == "cpu":
        return "cpu"
    if requested == "mps":
        if not getattr(torch.backends, "mps", None) or not torch.backends.mps.is_available():
            raise RuntimeError("MPS was explicitly selected but is not available.")
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_chatterbox(model_name: str, device_pref: str):
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = _select_device(torch, device_pref)
    t3_model = model_name if model_name in ("v2", "v3") else "v3"
    print(f"[tts_server] Loading Chatterbox Multilingual {t3_model.upper()} on {device}...", flush=True)
    model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model=t3_model)
    return model, device, f"Chatterbox Multilingual {t3_model.upper()}", model.sr, _package_version("chatterbox-tts")


def _load_qwen(model_name: str, device_pref: str):
    import torch
    from qwen_tts import Qwen3TTSModel

    device = _select_device(torch, device_pref)
    if device == "mps":
        raise RuntimeError("Qwen3-TTS is not enabled on MPS in AmiorAI v40. Use CPU or CUDA.")

    if device == "cuda":
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        device_map = "cuda:0"
    else:
        dtype = torch.float32
        device_map = "cpu"

    kwargs = {"device_map": device_map, "dtype": dtype}
    # FlashAttention is optional. SDPA/eager remains the portable path when unavailable.
    if device == "cuda":
        try:
            import flash_attn  # noqa: F401
            kwargs["attn_implementation"] = "flash_attention_2"
            print("[tts_server] Qwen3-TTS: FlashAttention 2 detected.", flush=True)
        except Exception:
            kwargs["attn_implementation"] = "sdpa"
            print("[tts_server] Qwen3-TTS: FlashAttention 2 unavailable, using SDPA.", flush=True)

    print(f"[tts_server] Loading {model_name} on {device}...", flush=True)
    model = Qwen3TTSModel.from_pretrained(model_name, **kwargs)
    return model, device, model_name, None, _package_version("qwen-tts")


def _load_model(engine: str, model_name: str, device_pref: str):
    global _MODEL
    try:
        STATE.update({"status": "loading", "engine": engine, "device": None, "error": None, "model": model_name})
        if engine == "qwen":
            model, device, resolved_name, sample_rate, package_version = _load_qwen(model_name, device_pref)
        else:
            model, device, resolved_name, sample_rate, package_version = _load_chatterbox(model_name, device_pref)
        _MODEL = model
        STATE.update({
            "status": "ready", "device": device, "model": resolved_name,
            "sample_rate": sample_rate, "package_version": package_version,
        })
        print(f"[tts_server] Ready: {resolved_name} on {device}.", flush=True)
    except Exception as exc:  # noqa: BLE001
        STATE["status"] = "error"
        STATE["error"] = str(exc)
        traceback.print_exc()


@app.get("/health")
def health():
    return jsonify(dict(STATE))


def _exit_process_after_response():
    # Process exit is the most reliable cross-model CUDA offload: every PyTorch allocation
    # and CUDA context is returned to the driver. The main app autostarts us on next speech.
    import time
    time.sleep(0.15)
    os._exit(0)


@app.post("/shutdown")
def shutdown():
    if request.remote_addr not in ("127.0.0.1", "::1", None):
        return jsonify({"ok": False, "error": "Local requests only."}), 403
    STATE["status"] = "stopping"
    threading.Thread(target=_exit_process_after_response, daemon=True).start()
    return jsonify({"ok": True, "message": "TTS process stopping; CUDA VRAM will be released."})


def _ffmpeg_executable() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _normalise_reference_audio(source: str) -> tuple[str, bool]:
    """Return a clean mono 24 kHz WAV path and whether it must be deleted."""
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"Voice sample not found: {source}")

    fd, out_path = tempfile.mkstemp(prefix="amiorai_voice_", suffix=".wav")
    os.close(fd)
    try:
        import librosa
        import soundfile as sf
        wav, _ = librosa.load(str(source_path), sr=24000, mono=True)
        if wav is None or len(wav) < 2400:
            raise ValueError("The voice sample is empty or shorter than 0.1 second.")
        sf.write(out_path, wav, 24000, subtype="PCM_16")
        return out_path, True
    except Exception as first_error:
        ffmpeg = _ffmpeg_executable()
        if not ffmpeg:
            try:
                os.remove(out_path)
            except OSError:
                pass
            raise RuntimeError(
                "The voice sample could not be decoded. Use WAV, FLAC or MP3, or reinstall the "
                f"voice environment to restore its bundled FFmpeg decoder. Detail: {first_error}"
            ) from first_error
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source_path),
             "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", out_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
            try:
                os.remove(out_path)
            except OSError:
                pass
            raise RuntimeError(f"FFmpeg could not decode the voice sample: {proc.stderr.strip()}")
        return out_path, True


@app.post("/clone_check")
def clone_check():
    data = request.get_json(force=True, silent=False) or {}
    path = str(data.get("speaker_wav") or "").strip()
    normalised = None
    remove_normalised = False
    try:
        normalised, remove_normalised = _normalise_reference_audio(path)
        import soundfile as sf
        info = sf.info(normalised)
        duration = float(info.frames) / float(info.samplerate or 1)
        if duration < 2.0:
            return jsonify({"ok": False, "error": "Voice sample is too short; use at least 2 seconds."}), 400
        return jsonify({"ok": True, "duration": round(duration, 2), "sample_rate": info.samplerate})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        if normalised and remove_normalised:
            try:
                os.remove(normalised)
            except OSError:
                pass


def clean_text_for_speech(text: str) -> str:
    """Remove visual markup while preserving the words and punctuation meant to be spoken."""
    text = html.unescape(str(text or ""))
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("*", "").replace("_", "").replace("#", "")
    text = re.sub(r"^\s*>+\s?", "", text, flags=re.MULTILINE)
    # Remove control and private-use characters, plus pictographic symbols that TTS models
    # frequently pronounce as noise. Keep normal punctuation, currency and mathematical text.
    cleaned = []
    for char in text:
        category = unicodedata.category(char)
        if category in ("Cc", "Cf", "Co", "Cs") and char not in "\n\t":
            continue
        if category == "So":
            continue
        cleaned.append(char)
    text = "".join(cleaned)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_long_segment(segment: str, max_chars: int) -> list[str]:
    if len(segment) <= max_chars:
        return [segment]
    pieces = re.split(r"(?<=[,;:—–-])\s+", segment)
    if len(pieces) == 1:
        pieces = segment.split()
        word_mode = True
    else:
        word_mode = False
    out, current = [], ""
    for piece in pieces:
        sep = " "
        candidate = (current + sep + piece).strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            out.append(current)
        if len(piece) <= max_chars:
            current = piece
            continue
        # Last-resort hard wrap only for pathological unbroken strings.
        out.extend(piece[i:i + max_chars] for i in range(0, len(piece), max_chars))
        current = ""
    if current:
        out.append(current)
    if word_mode:
        return [x.strip() for x in out if x.strip()]
    return out


def split_into_chunks(text: str, max_chars: int) -> list[str]:
    text = clean_text_for_speech(text)
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?…])\s+|\n+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    chunks, current = [], ""
    for sentence in sentences:
        for piece in _split_long_segment(sentence, max_chars):
            candidate = f"{current} {piece}".strip() if current else piece
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _clamp(value, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return max(minimum, min(maximum, value))


def _as_mono_float32(wav):
    import numpy as np
    try:
        import torch
        if isinstance(wav, torch.Tensor):
            wav = wav.detach().float().cpu().numpy()
    except Exception:
        pass
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim == 2:
        # Most model outputs are [1, samples]. Handle [samples, channels] as well.
        arr = arr[0] if arr.shape[0] <= arr.shape[1] else arr.mean(axis=1)
    elif arr.ndim > 2:
        arr = arr.reshape(-1)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return arr.reshape(-1)


def _join_audio(parts, sample_rate: int):
    import numpy as np
    valid = [p for p in parts if p is not None and len(p)]
    if not valid:
        raise RuntimeError("The TTS model returned empty audio.")
    pause = np.zeros(max(1, int(sample_rate * 0.12)), dtype=np.float32)
    joined = []
    for index, part in enumerate(valid):
        joined.append(part)
        if index + 1 < len(valid):
            joined.append(pause)
    return np.concatenate(joined)


def _finish_audio(wav, sample_rate: int, speed: float):
    import numpy as np
    wav = _as_mono_float32(wav)
    if abs(speed - 1.0) > 0.01:
        import librosa
        wav = librosa.effects.time_stretch(wav, rate=speed)
    peak = float(np.max(np.abs(wav))) if len(wav) else 0.0
    if peak > 0.98:
        wav = wav * (0.98 / peak)
    return np.asarray(wav, dtype=np.float32)


def _generate_chatterbox(chunks: list[str], language: str, reference_wav: str,
                         exaggeration: float, cfg_weight: float, temperature: float):
    language = language.lower()
    if language not in CHATTERBOX_LANGUAGES:
        raise ValueError(f"Chatterbox does not support language '{language}'.")
    # Analyse the reference only once, then reuse exactly the same speaker conditionals for
    # every sentence-aware chunk. Both methods are part of Chatterbox's upstream class API.
    _MODEL.prepare_conditionals(reference_wav, exaggeration=exaggeration)
    parts = []
    for chunk in chunks:
        wav = _MODEL.generate(
            chunk, language_id=language, exaggeration=exaggeration,
            cfg_weight=cfg_weight, temperature=temperature,
        )
        parts.append(_as_mono_float32(wav))
    return _join_audio(parts, int(_MODEL.sr)), int(_MODEL.sr)


def _qwen_prompt(reference_wav: str, reference_text: str, cache_source: str | None = None):
    # The decoded WAV is temporary, so key the cache with the persistent character sample.
    # A modified source file or transcript automatically creates a fresh prompt.
    source = cache_source or reference_wav
    stat = os.stat(source)
    use_text = bool(reference_text.strip())
    key = (source, stat.st_size, stat.st_mtime_ns, reference_text.strip())
    cached = _QWEN_PROMPTS.get(key)
    if cached is not None:
        _QWEN_PROMPTS.move_to_end(key)
        return cached
    kwargs = {"ref_audio": reference_wav, "x_vector_only_mode": not use_text}
    if use_text:
        kwargs["ref_text"] = reference_text.strip()
    prompt = _MODEL.create_voice_clone_prompt(**kwargs)
    _QWEN_PROMPTS[key] = prompt
    _QWEN_PROMPTS.move_to_end(key)
    while len(_QWEN_PROMPTS) > _QWEN_PROMPT_CACHE_SIZE:
        _QWEN_PROMPTS.popitem(last=False)
    return prompt


def _generate_qwen(chunks: list[str], language: str, reference_wav: str, reference_text: str,
                   cache_source: str | None = None):
    qwen_language = QWEN_LANGUAGE_NAMES.get(language.lower(), "Auto")
    prompt = _qwen_prompt(reference_wav, reference_text, cache_source=cache_source)
    parts, sample_rate = [], None
    for chunk in chunks:
        wavs, sr = _MODEL.generate_voice_clone(
            text=chunk, language=qwen_language, voice_clone_prompt=prompt,
        )
        if not wavs:
            raise RuntimeError("Qwen3-TTS returned no waveform.")
        parts.append(_as_mono_float32(wavs[0]))
        sample_rate = int(sr)
    return _join_audio(parts, sample_rate), sample_rate


@app.post("/tts")
def tts():
    if STATE["status"] != "ready" or _MODEL is None:
        return jsonify({"error": f"TTS model is not ready (status={STATE['status']})."}), 503

    data = request.get_json(force=True, silent=False) or {}
    text = str(data.get("text") or "").strip()
    language = str(data.get("language") or "fr").strip().lower()
    speaker_wav = str(data.get("speaker_wav") or "").strip()
    reference_text = str(data.get("reference_text") or "").strip()
    speed = _clamp(data.get("speed"), 1.0, 0.75, 1.25)
    exaggeration = _clamp(data.get("exaggeration"), 0.5, 0.25, 2.0)
    cfg_weight = _clamp(data.get("cfg_weight"), 0.5, 0.0, 1.0)
    temperature = _clamp(data.get("temperature"), 0.8, 0.05, 2.0)

    if not text:
        return jsonify({"error": "Empty text."}), 400
    if not speaker_wav or not os.path.isfile(speaker_wav):
        return jsonify({"error": f"Voice sample not found: {speaker_wav}"}), 400

    max_chars = 280 if STATE["engine"] == "chatterbox" else 520
    chunks = split_into_chunks(text, max_chars=max_chars)
    if not chunks:
        return jsonify({"error": "The message contains no speakable text after cleanup."}), 400

    reference_wav = None
    remove_reference_wav = False
    audio_buffer = None
    try:
        reference_wav, remove_reference_wav = _normalise_reference_audio(speaker_wav)
        with _LOCK:
            if STATE["engine"] == "qwen":
                wav, sample_rate = _generate_qwen(
                    chunks, language, reference_wav, reference_text, cache_source=speaker_wav,
                )
            else:
                wav, sample_rate = _generate_chatterbox(
                    chunks, language, reference_wav, exaggeration, cfg_weight, temperature,
                )
            wav = _finish_audio(wav, sample_rate, speed)
            import soundfile as sf
            audio_buffer = io.BytesIO()
            sf.write(audio_buffer, wav, sample_rate, format="WAV", subtype="PCM_16")
            audio_buffer.seek(0)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc), "engine": STATE["engine"]}), 500
    finally:
        if reference_wav and remove_reference_wav:
            try:
                os.remove(reference_wav)
            except OSError:
                pass

    if audio_buffer is None:
        return jsonify({"error": "The TTS model returned no audio buffer."}), 500
    return send_file(
        audio_buffer, mimetype="audio/wav", as_attachment=False,
        download_name="amiorai_voice.wav", conditional=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8810)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--engine", choices=("chatterbox", "qwen"), default="chatterbox")
    parser.add_argument("--model", default="v3")
    parser.add_argument("--device", default="auto", help="auto | cuda | cpu | mps")
    args = parser.parse_args()

    engine = args.engine.lower()
    model_name = args.model
    if engine == "qwen" and model_name in ("v2", "v3", ""):
        model_name = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    if engine == "chatterbox" and model_name not in ("v2", "v3"):
        model_name = "v3"

    STATE["engine"] = engine
    STATE["model"] = model_name
    threading.Thread(
        target=_load_model, args=(engine, model_name, args.device), daemon=True,
    ).start()
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
