from __future__ import annotations

from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.security.secret_store import InMemorySecretStore


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "db_provider_cli.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.close()


async def test_provider_cli_status_list_via_bridge_never_crashes(ctx) -> None:
    # Real, unmocked discovery -- must be safe on any machine, with or
    # without codex/claude/gemini actually installed (spec §74).
    result = await dispatch("provider.cli.status.list", {}, ctx)
    assert set(result.keys()) == {"codex_cli", "claude_code_cli", "gemini_cli"}
    for status in result.values():
        assert "state" in status
        assert "access_method" in status
