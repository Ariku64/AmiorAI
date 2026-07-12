# AmiorAI v40.0.6 — local voice engines

This folder contains the shared local TTS server and two isolated installers.

## Windows: no system Python required

Each Windows installer downloads its own official CPython embeddable runtime:

- `python_chatterbox` — Python 3.11.9 for Chatterbox;
- `python_qwen` — Python 3.12.10 for Qwen3-TTS.

These runtimes are completely separate from AmiorAI's main `python_embed`, from one another, and from any Python installed on Windows. No PATH modification is made.

## Default: Chatterbox Multilingual V3

Run `install.bat`. It creates `python_chatterbox`, installs the CUDA runtime and leaves Qwen untouched. Select **Chatterbox Multilingual V3** in AmiorAI.

## Optional: Qwen3-TTS 0.6B Base

Run `install_qwen.bat` only when the experimental engine is wanted. It creates `python_qwen` and does not alter Chatterbox.

For the strongest Qwen clone, enter the exact transcript of the reference sample in the character editor. If it repeats part of that sample, remove the transcript to use speaker-embedding mode or return to Chatterbox.

## Automatic VRAM swap

With **Release VRAM between engines** enabled, AmiorAI coordinates the GPU as follows:

1. Before LM Studio or ComfyUI loads a model, the CUDA TTS process is stopped.
2. Stopping the process releases its full PyTorch CUDA context and VRAM.
3. At the next spoken reply, AmiorAI releases LM Studio and idle ComfyUI models, then starts the selected TTS runtime again.
4. CPU TTS is not stopped because it occupies no GPU VRAM.

This mode is recommended for 16 GB GPUs. It can be disabled on machines with enough VRAM to keep several models loaded simultaneously.

## Important

- Model weights download on first use and are not included in AmiorAI.
- Use only voices you own or have clear permission to use.
- The local server listens on `127.0.0.1:8810` by default.
- Do not merge or rename the two embedded runtimes.
- Windows installers target NVIDIA RTX GPUs by default. For CPU-only Chatterbox, set `TORCH_INDEX=cpu` in `install.bat` before running it; CPU generation is much slower.
- Linux/macOS installers still use isolated virtual environments because CPython does not publish the same embeddable Windows package format for those platforms.

See `../THIRD_PARTY_NOTICES.md` for source and licence information.

### Réparer Chatterbox

Si AmiorAI signale `No module named 'chatterbox'`, ferme l'application puis lance
`tts_server\repair_chatterbox.bat`. Le script réutilise le Python Embedded existant,
répare pip et réinstalle le paquet officiel sans nécessiter Python sur Windows.
Le diagnostic détaillé est conservé dans `tts_server\install_chatterbox_pip.log`.
