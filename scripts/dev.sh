#!/usr/bin/env bash
# Starts the Orquestrador desktop app in development mode on macOS/Linux.
# Run scripts/setup.sh first if you have not already.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -d ".venv" ]; then
  echo "No .venv found. Run scripts/setup.sh first." >&2
  exit 1
fi

cd desktop
npm run tauri dev
