# Starts the Orquestrador desktop app in development mode on Windows.
# Run scripts/setup.ps1 first if you have not already.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    Write-Error "No .venv found. Run scripts/setup.ps1 first."
    exit 1
}

Push-Location desktop
npm run tauri dev
Pop-Location
