#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$ROOT_DIR"

mkdir -p "$HOME/.local/bin"
ln -sf "$VENV_DIR/bin/instagram" "$HOME/.local/bin/instagram"

echo "Installed instagram CLI."
echo "Command path: $HOME/.local/bin/instagram"
echo "Now run: instagram"

