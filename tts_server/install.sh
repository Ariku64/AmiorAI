#!/usr/bin/env bash
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-$(command -v python3.11 || command -v python3.12 || command -v python3)}"
VENV="venv_chatterbox"
TORCH_INDEX="${TORCH_INDEX:-cu128}"

"$PYTHON" -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip setuptools wheel
if [[ "$(uname -s)" == "Darwin" ]]; then
  python -m pip install --upgrade --force-reinstall torch==2.8.0 torchaudio==2.8.0
else
  python -m pip install --upgrade --force-reinstall torch==2.8.0 torchaudio==2.8.0 \
    --index-url "https://download.pytorch.org/whl/${TORCH_INDEX}"
fi
python -m pip install \
  "numpy>=1.24,<2" "librosa==0.11.0" s3tokenizer \
  "transformers==5.2.0" "diffusers==0.29.0" \
  "conformer==0.3.2" "safetensors==0.5.3" \
  spacy-pkuseg "pykakasi==2.3.0" pyloudnorm omegaconf \
  flask soundfile imageio-ffmpeg
python -m pip install "https://github.com/resemble-ai/Perth/archive/refs/heads/master.zip"
python -m pip install "chatterbox-tts==0.1.7" --no-deps
python -c "import torch; from chatterbox.mtl_tts import ChatterboxMultilingualTTS; print('Chatterbox OK, torch', torch.__version__)"
printf 'ok\n' > "$VENV/.installed"
echo "Chatterbox Multilingual V3 installed. Model weights download on first start."
