"""Genuinely-live Codex CLI test: actually spawns the real, installed
`codex` binary and talks to the real ChatGPT-account-authenticated
session. Skipped unless `RUN_LIVE_AI_TESTS=true` is set AND `codex` is
actually installed and logged in -- never required, never run in CI by
default (see `docs/DEVELOPMENT.md`), so a developer/CI machine without
Codex installed never sees a failure here, only a skip.
"""

from __future__ import annotations

import os
import shutil

import pytest
from core.providers.base import AIRequest, ProviderConnectionState
from core.providers.codex_cli_provider import CodexCliProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AI_TESTS") != "true" or shutil.which("codex") is None,
    reason="Live Codex CLI test: set RUN_LIVE_AI_TESTS=true with `codex` installed to run.",
)


async def test_real_codex_cli_answers_a_trivial_prompt(tmp_path) -> None:
    provider = CodexCliProvider()
    status = await provider.get_status()
    if status.state != ProviderConnectionState.CONNECTED:
        pytest.skip(f"codex CLI is installed but not authenticated ({status.detail!r}).")

    request = AIRequest.simple(
        execution_id="live_probe", agent_id="agent_generalist",
        system_prompt="You are a terse assistant.",
        prompt="Reply with exactly the text: PROBE_OK",
        workspace_path=str(tmp_path), timeout_seconds=60.0,
        metadata={"risk": "low"},  # -> read-only sandbox, no file writes expected
    )
    response = await provider.execute(request)

    assert "PROBE_OK" in response.content
    assert response.usage.input_tokens > 0
