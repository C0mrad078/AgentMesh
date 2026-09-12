"""Genuinely-live Claude Code CLI test: actually spawns the real, installed
`claude` binary. Skipped unless `RUN_LIVE_AI_TESTS=true` is set AND
`claude` is actually installed and logged in -- never required, never run
in CI by default. See `test_codex_cli_provider_live.py` for the same
rationale.
"""

from __future__ import annotations

import os
import shutil

import pytest
from core.providers.base import AIRequest, ProviderConnectionState
from core.providers.claude_code_cli_provider import ClaudeCodeCliProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AI_TESTS") != "true" or shutil.which("claude") is None,
    reason="Live Claude Code CLI test: set RUN_LIVE_AI_TESTS=true with `claude` installed to run.",
)


async def test_real_claude_code_cli_answers_a_trivial_prompt(tmp_path) -> None:
    provider = ClaudeCodeCliProvider()
    status = await provider.get_status()
    if status.state != ProviderConnectionState.CONNECTED:
        pytest.skip(f"claude CLI is installed but not authenticated ({status.detail!r}).")

    request = AIRequest.simple(
        execution_id="live_probe", agent_id="agent_generalist",
        system_prompt="You are a terse assistant.",
        prompt="Reply with exactly the text: PROBE_OK",
        workspace_path=str(tmp_path), timeout_seconds=60.0,
        metadata={"risk": "low"},  # -> plan mode, no file writes expected
    )
    response = await provider.execute(request)

    assert "PROBE_OK" in response.content
    assert response.usage.input_tokens >= 0


async def test_real_claude_code_cli_creates_a_file_when_risk_allows_writes(tmp_path) -> None:
    provider = ClaudeCodeCliProvider()
    status = await provider.get_status()
    if status.state != ProviderConnectionState.CONNECTED:
        pytest.skip(f"claude CLI is installed but not authenticated ({status.detail!r}).")

    request = AIRequest.simple(
        execution_id="live_probe_write", agent_id="agent_coder",
        system_prompt="You are a coder.",
        prompt="Create a file called live_probe.txt containing exactly PROBE_WRITE_OK",
        workspace_path=str(tmp_path), timeout_seconds=60.0,
        metadata={"risk": "medium"},  # -> acceptEdits mode, writes expected
    )
    response = await provider.execute(request)

    created = tmp_path / "live_probe.txt"
    assert created.exists()
    assert "PROBE_WRITE_OK" in created.read_text()
    assert response.structured_output is not None
    assert response.structured_output["changed_files"]
