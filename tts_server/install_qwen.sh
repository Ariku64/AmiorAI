#!/usr/bin/env bash
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-$(command -v python3.12 || command -v python3.11 || command -v python3)}"
VENV="venv_qwen"
TORCH_INDEX="${TORCH_INDEX:-cu128}"

"$PYTHON" -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip setuptools wheel
if [[ "$(uname -s)" == "Darwin" ]]; then
  python -m pip install --upgrade torch==2.8.0 torchaudio==2.8.0
else
  python -m pip install --upgrade torch==2.8.0 torchaudio==2.8.0 \
    --index-url "https://download.pytorch.org/whl/${TORCH_INDEX}"
fi
python -m pip install "qwen-tts==0.1.1" flask soundfile imageio-ffmpeg
python -c "import torch; from qwen_tts import Qwen3TTSModel; print('Qwen3-TTS OK, torch', torch.__version__)"
printf 'ok\n' > "$VENV/.installed"
echo "Optional Qwen3-TTS installed. Select it in AmiorAI and restart TTS."
