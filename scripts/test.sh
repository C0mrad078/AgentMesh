#!/usr/bin/env bash
# Runs every test/lint/typecheck suite in the repository, in the same order
# used for the Stage 1 quality gate. Exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "==> Python: ruff"
.venv/bin/ruff check core tests

echo "==> Python: mypy"
.venv/bin/mypy core

echo "==> Python: pytest (unit, integration, smoke)"
.venv/bin/python -m pytest tests/python tests/integration tests/smoke

echo "==> Frontend: typecheck"
(cd desktop && npm run typecheck)

echo "==> Frontend: lint"
(cd desktop && npm run lint)

echo "==> Frontend: vitest"
(cd desktop && npm run test)

echo "==> Frontend: build"
(cd desktop && npm run build)

echo "==> Rust: fmt --check"
(cd desktop/src-tauri && cargo fmt -- --check)

echo "==> Rust: clippy"
(cd desktop/src-tauri && cargo clippy --all-targets -- -D warnings)

echo "==> Rust: cargo test"
(cd desktop/src-tauri && cargo test)

echo "==> All checks passed."
