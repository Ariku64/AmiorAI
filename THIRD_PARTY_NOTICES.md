# AmiorAI v40.0.4 — Third-party notices

AmiorAI is a free orchestration application. It does not bundle LM Studio, ComfyUI, language-model weights, image-model weights or voice-model weights. Those components are downloaded or installed separately and remain governed by their own licences and terms.

This notice highlights the optional voice engines introduced in v40. It is not a replacement for the licence files shipped by each dependency.

## Chatterbox Multilingual V3

- Project: Resemble AI Chatterbox
- Source: https://github.com/resemble-ai/chatterbox
- Licence stated by the upstream project: MIT
- AmiorAI use: default optional local TTS and voice-cloning engine
- Installation: `tts_server/install.bat` into the isolated `tts_server/python_chatterbox` embedded runtime

The engine and model files are not included in the AmiorAI archive. The installer first retrieves an official CPython embeddable package from python.org, then retrieves the Python package and dependencies from their upstream distribution sources.

## Qwen3-TTS 0.6B Base

- Project: Qwen3-TTS
- Source: https://github.com/QwenLM/Qwen3-TTS
- Default model identifier: `Qwen/Qwen3-TTS-12Hz-0.6B-Base`
- Licence stated by the upstream project: Apache License 2.0
- AmiorAI use: optional experimental local TTS and voice-cloning engine
- Installation: `tts_server/install_qwen.bat` into the isolated `tts_server/python_qwen` embedded runtime

The engine and model files are not included in the AmiorAI archive. Users should review the current upstream model card and licence before downloading or redistributing any model.

## User responsibility for voices

A software or model licence does not grant rights over a person’s voice or identity. Users must only import, clone or publish voices they own, voices in the public domain, or voices for which they have clear and valid permission. Synthetic voices must not be used for impersonation, deception, harassment, defamation, fraud or to bypass consent.

## Other dependencies

Python packages installed by AmiorAI or either TTS installer retain their own licences. Their authoritative licence texts are available in the installed package metadata and upstream repositories. Distributors should keep those notices intact and review them before repackaging dependencies or model weights.
