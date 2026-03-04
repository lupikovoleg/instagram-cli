#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

pick_python() {
  local candidate
  for candidate in python3.12 python3.11 python3.10 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON_BIN="$(pick_python)"; then
  echo "Error: instagram-cli requires Python 3.10 or newer."
  echo "Current system python3 is too old or Python 3.10+ is not installed."
  echo
  echo "On macOS with Homebrew:"
  echo "  brew install python@3.11"
  echo
  echo "Then run ./install.sh again."
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$ROOT_DIR"

mkdir -p "$HOME/.local/bin"
ln -sf "$VENV_DIR/bin/instagram" "$HOME/.local/bin/instagram"
ln -sf "$VENV_DIR/bin/instagram-mcp" "$HOME/.local/bin/instagram-mcp"

echo "Installed instagram CLI."
echo "Python: $("$VENV_DIR/bin/python" --version 2>&1)"
echo "Command path: $HOME/.local/bin/instagram"
echo "MCP path: $HOME/.local/bin/instagram-mcp"
echo "Now run: instagram"
