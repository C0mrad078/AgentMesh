# Bootstraps the development environment on Windows:
#   - creates the Python virtual environment used by the core (and by the
#     dev-mode sidecar launch in desktop/src-tauri/src/bridge/process.rs)
#   - installs the core's Python dependencies
#   - installs the frontend's npm dependencies
#
# Safe to re-run; every step is idempotent.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    Write-Host "==> Creating Python virtual environment (.venv)"
    python -m venv .venv
}

Write-Host "==> Installing core Python dependencies"
& .\.venv\Scripts\pip.exe install --quiet --upgrade pip
& .\.venv\Scripts\pip.exe install --quiet -e ".[dev]"

Write-Host "==> Installing desktop npm dependencies"
Push-Location desktop
npm install
Pop-Location

Write-Host "==> Done. Run scripts/dev.ps1 to start the app in development mode."
