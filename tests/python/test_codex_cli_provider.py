"""Tests for `CodexCliProvider`.

Two tiers, matching the project's testing policy (see `docs/DEVELOPMENT.md`):

  * Unit tests below mock `ShellRunner.run` -- no real subprocess, no real
    Codex CLI required, always run.
  * `test_codex_cli_provider_live.py` actually invokes the installed
    `codex` binary and is skipped unless `RUN_LIVE_AI_TESTS=true` is set
    AND `codex` is genuinely installed and authenticated -- never run by
    default, never required in CI.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from core.providers.base import AIRequest, ProviderConnectionState
from core.providers.codex_cli_provider import CodexCliProvider
from core.providers.exceptions import ProviderInvalidResponseError, ProviderUnavailableError
from core.utils.shell_runner import RunResult

SUCCESS_JSONL = (
    '{"type":"thread.started","thread_id":"t1"}\n'
    '{"type":"turn.started"}\n'
    '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"done"}}\n'
    '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\n'
)

TURN_FAILED_JSONL = (
    '{"type":"thread.started","thread_id":"t1"}\n'
    '{"type":"turn.failed","error":{"message":"bad model"}}\n'
)


def _request(**overrides: object) -> AIRequest:
    return AIRequest.simple(
        execution_id="exec_1", agent_id="agent_coder", system_prompt="You are a coder.",
        prompt="fix the bug", workspace_path="/tmp/some-workspace", **overrides,
    )


async def test_execute_returns_a_normalized_response_on_success() -> None:
    provider = CodexCliProvider()
    fake_result = RunResult(success=True, stdout=SUCCESS_JSONL, stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/codex"),
        patch.object(provider._runner, "run", new=AsyncMock(return_value=fake_result)) as mock_run,
    ):
        response = await provider.execute(_request())

    assert response.content == "done"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 2
    argv = mock_run.call_args.args[0]
    assert argv[0] == "codex"
    assert "exec" in argv
    assert "--json" in argv
    assert argv[-1] == "-"  # prompt goes via stdin, never argv
    assert mock_run.call_args.kwargs["stdin_data"] is not None


async def test_execute_never_forwards_the_registry_default_sentinel_as_a_model() -> None:
    # Real bug, caught live: `ModelRegistry`'s codex_cli entry uses
    # `model_id="default"` as a sentinel meaning "let the CLI choose" --
    # but `routing.model` is never empty, so it always arrives in
    # `request.metadata["model"]` as the literal string "default". A naive
    # `if requested_model:` check is truthy for it and forwards `-m
    # default`, which Codex rejects with a real 400 (verified against the
    # actual CLI). No `-m`/`--model` flag must ever be added for it.
    provider = CodexCliProvider()
    fake_result = RunResult(success=True, stdout=SUCCESS_JSONL, stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/codex"),
        patch.object(provider._runner, "run", new=AsyncMock(return_value=fake_result)) as mock_run,
    ):
        await provider.execute(_request(metadata={"model": "default"}))

    argv = mock_run.call_args.args[0]
    assert "-m" not in argv


async def test_execute_raises_even_though_process_exits_zero_on_turn_failed() -> None:
    # Real, verified Codex CLI behavior: a turn.failed event can arrive
    # with exit code 0 -- the adapter must not treat that as success.
    provider = CodexCliProvider()
    fake_result = RunResult(success=True, stdout=TURN_FAILED_JSONL, stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/codex"),
        patch.object(provider._runner, "run", new=AsyncMock(return_value=fake_result)),
    ):
        with pytest.raises(ProviderInvalidResponseError):
            await provider.execute(_request())


async def test_execute_raises_when_the_process_itself_fails() -> None:
    provider = CodexCliProvider()
    fake_result = RunResult(success=False, stdout="", stderr="boom", returncode=1)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/codex"),
        patch.object(provider._runner, "run", new=AsyncMock(return_value=fake_result)),
    ):
        with pytest.raises(ProviderUnavailableError):
            await provider.execute(_request())


async def test_get_status_reports_not_installed_when_binary_is_missing() -> None:
    provider = CodexCliProvider()
    with patch.object(provider, "binary_path", return_value=None):
        status = await provider.get_status()
    assert status.state == ProviderConnectionState.NOT_INSTALLED


async def test_get_status_reports_connected_and_parses_auth_method() -> None:
    provider = CodexCliProvider()
    version_result = RunResult(success=True, stdout="codex-cli 0.154.0\n", stderr="", returncode=0)
    login_result = RunResult(success=True, stdout="Logged in using ChatGPT\n", stderr="", returncode=0)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/codex"),
        patch.object(
            provider._runner, "run", new=AsyncMock(side_effect=[version_result, login_result]),
        ),
    ):
        status = await provider.get_status()

    assert status.state == ProviderConnectionState.CONNECTED
    assert status.version == "codex-cli 0.154.0"
    assert status.auth_method == "ChatGPT"


async def test_get_status_reports_disconnected_when_not_logged_in() -> None:
    provider = CodexCliProvider()
    version_result = RunResult(success=True, stdout="codex-cli 0.154.0\n", stderr="", returncode=0)
    login_result = RunResult(success=False, stdout="Not logged in\n", stderr="", returncode=1)
    with (
        patch.object(provider, "binary_path", return_value="/usr/local/bin/codex"),
        patch.object(
            provider._runner, "run", new=AsyncMock(side_effect=[version_result, login_result]),
        ),
    ):
        status = await provider.get_status()

    assert status.state == ProviderConnectionState.DISCONNECTED
