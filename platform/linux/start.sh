#!/usr/bin/env bash
# Copyright 2026 Ariku
# SPDX-License-Identifier: Apache-2.0
# AmiorAI launcher. LM Studio and ComfyUI are external local services.
set -e
PYTHON="${PYTHON:-python3}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

LEGAL_VERSION="v40.0.5"
LEGAL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/AmiorAI"
LEGAL_MARKER="$LEGAL_DIR/legal_acceptance_${LEGAL_VERSION}.txt"
if [ ! -f "$LEGAL_MARKER" ]; then
  echo
  echo "============================================================"
  echo " Before using AmiorAI, read LEGAL_NOTICE.md"
  echo "============================================================"
  echo
  if [ -f "$ROOT/LEGAL_NOTICE.md" ]; then
    if command -v less >/dev/null 2>&1; then
      less "$ROOT/LEGAL_NOTICE.md"
    else
      cat "$ROOT/LEGAL_NOTICE.md"
    fi
  fi
  printf "I have read and accept the AmiorAI legal notice [y/N]: "
  read -r answer
  case "$answer" in
    y|Y|yes|YES|Yes) ;;
    *) echo "AmiorAI was not started because the legal notice was not accepted."; exit 1 ;;
  esac
  mkdir -p "$LEGAL_DIR"
  printf 'Accepted %s on %s\n' "$LEGAL_VERSION" "$(date -Is)" > "$LEGAL_MARKER"
fi

VENV=".venv"
VPY="$VENV/bin/python"

"$PYTHON" --version >/dev/null 2>&1 || { echo "Python 3.10 to 3.12 is required."; exit 1; }
[ -x "$VPY" ] || { echo "Creating local Python environment..."; "$PYTHON" -m venv "$VENV"; }
if [ ! -f "$VENV/.installed" ]; then
  "$VPY" -m pip install --upgrade pip
  "$VPY" -m pip install -r requirements.txt
  echo ok > "$VENV/.installed"
fi

echo "Starting AmiorAI on http://127.0.0.1:8800"
echo "Make sure the LM Studio local server is running."
( sleep 4; (xdg-open http://127.0.0.1:8800 || open http://127.0.0.1:8800) >/dev/null 2>&1 ) &
"$VPY" app.py
