# Runs every test/lint/typecheck suite in the repository, in the same order
# used for the Stage 1 quality gate. Exits non-zero on the first failure.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "==> Python: ruff"
.\.venv\Scripts\ruff.exe check core tests

Write-Host "==> Python: mypy"
.\.venv\Scripts\mypy.exe core

Write-Host "==> Python: pytest (unit, integration, smoke)"
.\.venv\Scripts\python.exe -m pytest tests/python tests/integration tests/smoke

Write-Host "==> Frontend: typecheck"
Push-Location desktop; npm run typecheck; Pop-Location

Write-Host "==> Frontend: lint"
Push-Location desktop; npm run lint; Pop-Location

Write-Host "==> Frontend: vitest"
Push-Location desktop; npm run test; Pop-Location

Write-Host "==> Frontend: build"
Push-Location desktop; npm run build; Pop-Location

Write-Host "==> Rust: fmt --check"
Push-Location desktop/src-tauri; cargo fmt -- --check; Pop-Location

Write-Host "==> Rust: clippy"
Push-Location desktop/src-tauri; cargo clippy --all-targets -- -D warnings; Pop-Location

Write-Host "==> Rust: cargo test"
Push-Location desktop/src-tauri; cargo test; Pop-Location

Write-Host "==> All checks passed."
