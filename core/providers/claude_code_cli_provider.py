"""Claude Code CLI provider: wraps the official `claude` CLI, never the
Anthropic Messages API directly -- see `core/providers/anthropic_provider.py`
for that. Authentication is entirely the CLI's own responsibility (`claude
auth login`, opening the official OAuth flow, or Console/API key setup);
this adapter only ever runs `claude auth status`, a read-only diagnostic
(structured JSON, unlike Codex's plain text), and never stores, extracts,
or reads the CLI's own credential files.

Non-interactive execution requires `--permission-prompts none`: without
it, any action that would normally prompt for confirmation hangs forever
waiting for an answer that can never arrive over a piped, non-interactive
invocation -- verified live, not assumed.
"""

from __future__ import annotations

import json
import time

from core.orchestrator.models import RiskLevel
from core.providers.base import (
    AIMessage,
    AIRequest,
    AIResponse,
    ProviderConnectionState,
    ProviderStatus,
    TokenUsage,
)
from core.providers.claude_events import parse_claude_stream_json
from core.providers.cli_provider import (
    CliProviderAdapter,
    claude_permission_mode_for,
    real_model_or_none,
)
from core.utils.errors import ProviderInvalidResponseError, ProviderUnavailableError
from core.utils.logging import get_logger

logger = get_logger("providers.claude_code_cli")


class ClaudeCodeCliProvider(CliProviderAdapter):
    name = "claude_code_cli"
    binary_name = "claude"

    async def get_status(self) -> ProviderStatus:
        if self.binary_path() is None:
            return ProviderStatus(
                access_method=self.access_method, state=ProviderConnectionState.NOT_INSTALLED,
                detail="`claude` was not found on PATH. Install the official Claude Code CLI, "
                       "then restart the Orquestrador.",
            )

        version_result = await self._run_cli(["claude", "--version"], cwd=None, timeout=10.0)
        version = version_result.stdout.strip() or None

        auth_result = await self._run_cli(["claude", "auth", "status"], cwd=None, timeout=10.0)
        auth_info = _parse_auth_status(auth_result.stdout)
        if not auth_result.success or not auth_info.get("loggedIn"):
            return ProviderStatus(
                access_method=self.access_method, state=ProviderConnectionState.DISCONNECTED,
                version=version, detail=auth_result.stdout.strip() or auth_result.stderr.strip() or None,
            )

        return ProviderStatus(
            access_method=self.access_method, state=ProviderConnectionState.CONNECTED,
            version=version,
            auth_method=str(auth_info.get("authMethod") or "unknown"),
            model="default",
            detail=str(auth_info.get("email")) if auth_info.get("email") else None,
        )

    async def execute(self, request: AIRequest) -> AIResponse:
        start = time.monotonic()
        # See `core.providers.codex_cli_provider.execute` for why this must
        # go through `real_model_or_none` and never a naive truthy check --
        # the registry's "default" sentinel is itself a non-empty string.
        model = real_model_or_none(request.metadata)
        risk = _risk_from_metadata(request.metadata)

        argv = [
            "claude", "--print", "--output-format", "stream-json", "--verbose",
            "--permission-mode", claude_permission_mode_for(risk),
            "--permission-prompts", "none",
        ]
        if request.metadata.get('mission_session'):
            tools = ['Read', 'Glob', 'Grep']
            if not request.metadata.get('read_only'):
                tools += ['Edit', 'Write']
                if request.metadata.get('can_run_terminal'):
                    tools += ['Bash']
            argv += ['--tools', ','.join(tools), '--strict-mcp-config', '--safe-mode']
        resume_id = request.metadata.get('resume_session_id')
        if isinstance(resume_id, str) and resume_id:
            argv += ['--resume', resume_id]
        if model:
            argv += ["--model", model]

        prompt = _render_prompt(request)
        result = await self._run_cli(
            argv, cwd=request.workspace_path, timeout=request.timeout_seconds,
            execution_id=request.execution_id, stdin_data=prompt.encode("utf-8"),
        )
        turn = parse_claude_stream_json(result.stdout)
        if not result.success:
            detail = turn.error_message or result.stderr or result.stdout[-1000:]
            raise ProviderUnavailableError(f"claude exited {result.returncode}: {detail[:1000]}")

        if turn.failed:
            raise ProviderInvalidResponseError(turn.error_message or "Claude Code reported a turn failure.")

        return AIResponse(
            content=turn.final_message,
            provider=self.name,
            model=model or "default",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=turn.input_tokens, output_tokens=turn.output_tokens),
            duration_seconds=time.monotonic() - start,
            structured_output={
                "session_id": turn.session_id,
                "cost_usd": turn.cost_usd,
                "num_turns": turn.num_turns,
                "changed_files": [
                    {"tool": t.name, "path": t.file_path} for t in turn.file_changes
                ],
            },
        )

    async def list_models(self) -> list[str]:
        # No models-list diagnostic; the app's own registry is the source
        # of truth, matching every other adapter's contract.
        return []


def _render_prompt(request: AIRequest) -> str:
    """Claude Code CLI takes one prompt per turn via `--print`, not a
    structured multi-message history -- flatten the conversation into a
    single text block, same scoped-down first version as the Codex
    adapter (no cross-step `--resume` yet)."""
    parts = [request.system_prompt] if request.system_prompt else []
    for message in request.messages:
        parts.append(_render_message(message))
    return "\n\n".join(parts)


def _render_message(message: AIMessage) -> str:
    if message.role.value == "tool":
        return f"[tool result: {message.tool_name}]\n{message.content}"
    return f"[{message.role.value}]\n{message.content}"


def _risk_from_metadata(metadata: dict[str, object]) -> RiskLevel:
    raw = metadata.get("risk")
    if isinstance(raw, str):
        try:
            return RiskLevel(raw)
        except ValueError:
            pass
    return RiskLevel.MEDIUM


def _parse_auth_status(stdout: str) -> dict[str, object]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
