"""Tests for `ClaudeCodeCliProvider`. See `test_codex_cli_provider.py` for
the same two-tier testing rationale (mocked unit tests here; a genuinely
live test gated behind `RUN_LIVE_AI_TESTS=true` in
`test_claude_code_cli_provider_live.py`)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from core.providers.base import AIRequest, ProviderConnectionState
from core.providers.claude_code_cli_provider import ClaudeCodeCliProvider
from core.providers.exceptions import ProviderInvalidResponseError, ProviderUnavailableError
from core.utils.shell_runner import RunResult

SUCCESS_STREAM = (
    '{"type":"system","subtype":"init","session_id":"s1"}\n'
    '{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}\n'
    '{"session_id":"s1","total_cost_usd":0.01,"usage":{"input_tokens":10,"output_tokens":2},'
    '"is_error":false,"num_turns":1,"result":"done","type":"result"}\n'
)

RESULT_ERROR_STREAM = (
    '{"type":"system","subtype":"init","session_id":"s2"}\n'
    '{"session_id":"s2","total_cost_usd":0.0,"usage":{"input_tokens":0,"output_tokens":0},'
    '"is_error":true,"num_turns":1,"result":"bad model","type":"result"}\n'
)


def _request(**overrides: object) -> AIRequest:
    return AIRequest.simple(
        execution_id="exec_1", agent_id="agent_coder", system_prompt="You are a coder.",
        prompt="fix the bug", workspace_path="/tmp/some-workspace", **overrides,
    )


async def test_execute_returns_a_normalized_response_on_success() -> None:
    provider = ClaudeCodeCliProvider()
    fake_result = RunResult(success=True, stdout=SUCCESS_STREAM, stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/claude"),
        patch.object(provider._runner, "run", new=AsyncMock(return_value=fake_result)) as mock_run,
    ):
        response = await provider.execute(_request())

    assert response.content == "done"
    assert response.usage.input_tokens == 10
    argv = mock_run.call_args.args[0]
    assert argv[0] == "claude"
    assert "--permission-prompts" in argv and "none" in argv
    assert mock_run.call_args.kwargs["stdin_data"] is not None


async def test_execute_never_forwards_the_registry_default_sentinel_as_a_model() -> None:
    # See the identical regression test in test_codex_cli_provider.py:
    # `ModelRegistry`'s claude_code_cli entry uses `model_id="default"` as
    # a sentinel, but `routing.model` is never empty, so it always arrives
    # as request.metadata["model"] == "default". No `--model` flag must
    # ever be added for it.
    provider = ClaudeCodeCliProvider()
    fake_result = RunResult(success=True, stdout=SUCCESS_STREAM, stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/claude"),
        patch.object(provider._runner, "run", new=AsyncMock(return_value=fake_result)) as mock_run,
    ):
        await provider.execute(_request(metadata={"model": "default"}))

    argv = mock_run.call_args.args[0]
    assert "--model" not in argv


async def test_execute_raises_when_is_error_true_even_though_process_exits_zero() -> None:
    provider = ClaudeCodeCliProvider()
    fake_result = RunResult(success=True, stdout=RESULT_ERROR_STREAM, stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/claude"),
        patch.object(provider._runner, "run", new=AsyncMock(return_value=fake_result)),
    ):
        with pytest.raises(ProviderInvalidResponseError):
            await provider.execute(_request())


async def test_execute_raises_when_the_process_itself_fails() -> None:
    provider = ClaudeCodeCliProvider()
    fake_result = RunResult(success=False, stdout="", stderr="boom", returncode=1)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/claude"),
        patch.object(provider._runner, "run", new=AsyncMock(return_value=fake_result)),
    ):
        with pytest.raises(ProviderUnavailableError):
            await provider.execute(_request())


async def test_get_status_reports_not_installed_when_binary_is_missing() -> None:
    provider = ClaudeCodeCliProvider()
    with patch.object(provider, "binary_path", return_value=None):
        status = await provider.get_status()
    assert status.state == ProviderConnectionState.NOT_INSTALLED


async def test_get_status_reports_connected_and_parses_json_auth_status() -> None:
    provider = ClaudeCodeCliProvider()
    version_result = RunResult(success=True, stdout="2.1.269 (Claude Code)\n", stderr="", returncode=0)
    auth_payload = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "user@example.com"})
    auth_result = RunResult(success=True, stdout=auth_payload, stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/claude"),
        patch.object(
            provider._runner, "run", new=AsyncMock(side_effect=[version_result, auth_result]),
        ),
    ):
        status = await provider.get_status()

    assert status.state == ProviderConnectionState.CONNECTED
    assert status.auth_method == "claude.ai"
    assert status.detail == "user@example.com"


async def test_get_status_reports_disconnected_when_not_logged_in() -> None:
    provider = ClaudeCodeCliProvider()
    version_result = RunResult(success=True, stdout="2.1.269 (Claude Code)\n", stderr="", returncode=0)
    auth_result = RunResult(success=True, stdout=json.dumps({"loggedIn": False}), stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/claude"),
        patch.object(
            provider._runner, "run", new=AsyncMock(side_effect=[version_result, auth_result]),
        ),
    ):
        status = await provider.get_status()

    assert status.state == ProviderConnectionState.DISCONNECTED
