"""Codex CLI provider: wraps the official `codex` CLI (`npm i -g
@openai/codex` / the standalone binary), never the OpenAI Chat Completions
API -- see `core/providers/openai_provider.py` for that, kept separate on
purpose (Stage 5 finding: the two were previously conflated under a single
"OpenAI (Codex)" label, which this adapter's introduction corrects).

Authentication is entirely the CLI's own responsibility (`codex login`,
opening the official ChatGPT OAuth flow or an API key via
`codex login --with-api-key`) -- this adapter only ever runs `codex login
status`, a read-only diagnostic, and never stores, extracts, or reads the
CLI's own credential files.
"""

from __future__ import annotations

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
from core.providers.cli_provider import CliProviderAdapter, real_model_or_none, sandbox_mode_for
from core.providers.codex_events import parse_codex_jsonl
from core.utils.errors import ProviderInvalidResponseError, ProviderUnavailableError
from core.utils.logging import get_logger

logger = get_logger("providers.codex_cli")

class CodexCliProvider(CliProviderAdapter):
    name = "codex_cli"
    binary_name = "codex"

    async def get_status(self) -> ProviderStatus:
        if self.binary_path() is None:
            return ProviderStatus(
                access_method=self.access_method, state=ProviderConnectionState.NOT_INSTALLED,
                detail="`codex` was not found on PATH. Install with `npm install -g @openai/codex` "
                       "or download the official binary, then restart the Orquestrador.",
            )

        version_result = await self._run_cli(["codex", "--version"], cwd=None, timeout=10.0)
        version = version_result.stdout.strip() or None

        login_result = await self._run_cli(["codex", "login", "status"], cwd=None, timeout=10.0)
        if not login_result.success:
            return ProviderStatus(
                access_method=self.access_method, state=ProviderConnectionState.DISCONNECTED,
                version=version, detail=login_result.stdout.strip() or login_result.stderr.strip() or None,
            )

        auth_text = login_result.stdout.strip()
        auth_method = auth_text.split(" using ", 1)[1] if " using " in auth_text else auth_text or None
        return ProviderStatus(
            access_method=self.access_method, state=ProviderConnectionState.CONNECTED,
            # Codex has no "list models"/"current model" diagnostic (see
            # `list_models()` below) -- "default" here means "whatever
            # `codex exec` uses when `-m` is not passed", not a specific,
            # reliably-known model id.
            version=version, auth_method=auth_method, model="default", detail=auth_text or None,
        )

    async def execute(self, request: AIRequest) -> AIResponse:
        start = time.monotonic()
        # Never guess a model id: Codex has no "list models" diagnostic to
        # validate one against (see `list_models()`), and a wrong id is a
        # hard 400 even though the process can exit 0 -- verified live
        # against the real CLI, which is exactly what caught this. Passing
        # no `-m` lets Codex use whatever its own config/account default
        # is. `real_model_or_none` also treats the registry's "default"
        # sentinel (see `core.providers.cli_provider`) as "no model
        # requested" -- routing.model is never empty, so a naive truthy
        # check would forward that sentinel itself as a literal `-m`
        # value, which the CLI rejects with its own 400 (also caught live).
        model = real_model_or_none(request.metadata)
        risk = _risk_from_metadata(request.metadata)
        argv = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", sandbox_mode_for(risk)]
        resume_id = request.metadata.get('resume_session_id')
        if isinstance(resume_id, str) and resume_id:
            # Parent exec flags retain the sandbox for this exact resumed session.
            argv += ['resume', resume_id]
        if model:
            argv += ["-m", model]
        if request.workspace_path and not resume_id:
            argv += ["-C", request.workspace_path]
        argv.append("-")  # read the prompt from stdin, never argv (no OS argv-length risk)

        prompt = _render_prompt(request)
        result = await self._run_cli(
            argv, cwd=request.workspace_path, timeout=request.timeout_seconds,
            execution_id=request.execution_id, stdin_data=prompt.encode("utf-8"),
        )
        if not result.success:
            raise ProviderUnavailableError(
                f"codex exec exited {result.returncode}: {(result.stderr or result.stdout)[:500]}"
            )

        turn = parse_codex_jsonl(result.stdout)
        if turn.failed:
            raise ProviderInvalidResponseError(turn.error_message or "Codex reported a turn failure.")

        return AIResponse(
            content=turn.final_message,
            provider=self.name,
            model=model or "default",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=turn.input_tokens, output_tokens=turn.output_tokens),
            duration_seconds=time.monotonic() - start,
            structured_output={
                "thread_id": turn.thread_id,
                "changed_files": [{"path": c.path, "kind": c.kind} for c in turn.file_changes],
                "commands": [
                    {"command": c.command, "exit_code": c.exit_code} for c in turn.commands
                ],
            },
        )

    async def list_models(self) -> list[str]:
        # Codex does not expose a models-list command; the app's own
        # registry (`core/providers/registry.py`) is the source of truth,
        # matching every other adapter's contract.
        return []


def _render_prompt(request: AIRequest) -> str:
    """Codex CLI takes one prompt per turn, not a structured multi-message
    chat history -- flatten the conversation into a single text block. A
    first, honest version: no session resume across steps yet (see
    `CliProviderAdapter`'s docstring on trust boundaries and the Stage 5
    report's noted follow-up work)."""
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
