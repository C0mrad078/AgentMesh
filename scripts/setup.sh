#!/usr/bin/env bash
# Bootstraps the development environment on macOS/Linux:
#   - creates the Python virtual environment used by the core (and by the
#     dev-mode sidecar launch in desktop/src-tauri/src/bridge/process.rs)
#   - installs the core's Python dependencies
#   - installs the frontend's npm dependencies
#
# Safe to re-run; every step is idempotent.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d ".venv" ]; then
  echo "==> Creating Python virtual environment (.venv)"
  "$PYTHON_BIN" -m venv .venv
fi

echo "==> Installing core Python dependencies"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[dev]"

echo "==> Installing desktop npm dependencies"
(cd desktop && npm install)

echo "==> Done. Run scripts/dev.sh to start the app in development mode."
