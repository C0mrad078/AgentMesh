"""Shared base for AI providers that are actually a locally-installed,
officially-authenticated CLI (Codex CLI, Claude Code CLI, Gemini CLI)
rather than an HTTP API this app calls with a stored key.

Trust boundary, stated explicitly rather than left implicit: a CLI adapter
delegates the entire step to that tool's own agentic loop, which reads and
writes the workspace directly through its own sandbox -- it does NOT go
through this app's `ToolExecutor`/Permission Engine
(`core.security.permissions`) the way an HTTP-API-routed step does. The
orchestrator's risk tier for the step still constrains this (see
`sandbox_mode_for`), but a CLI provider is a materially different trust
boundary than an HTTP provider and must never be presented to the user or
in logs as equivalent. See `docs/SECURITY.md`.

Authentication is never touched by this app: no token is extracted,
copied, or stored in SQLite. `get_status()` only ever shells out to the
CLI's own read-only diagnostic commands (`--version`, `login status`, ...).
"""

from __future__ import annotations

import asyncio
import shutil
from abc import abstractmethod
from pathlib import Path

from core.orchestrator.models import RiskLevel
from core.providers.base import (
    AIRequest,
    ProviderAccessMethod,
    ProviderAdapter,
    ProviderConnectionState,
    ProviderHealthStatus,
    ProviderStatus,
)
from core.utils.errors import ProviderUnavailableError, ToolDeniedError
from core.utils.logging import get_logger
from core.utils.shell_runner import RunResult, get_runner

logger = get_logger("providers.cli")


class CliProviderAdapter(ProviderAdapter):
    """Base for CLI-wrapped providers. Provides binary discovery and
    hardened subprocess execution (the same `ShellRunner` every other
    subprocess in this app goes through: minimal environment, output caps,
    real cancellation, timeout) -- never a raw, unaudited `subprocess.run`.
    """

    access_method = ProviderAccessMethod.CLI
    binary_name: str

    def __init__(self) -> None:
        self._runner = get_runner()
        self._cancel_events: dict[str, asyncio.Event] = {}

    def binary_path(self) -> str | None:
        return shutil.which(self.binary_name)

    @abstractmethod
    async def get_status(self) -> ProviderStatus:
        """Real, freshly-run diagnostics -- never a cached assumption."""
        ...

    async def health_check(self) -> ProviderHealthStatus:
        status = await self.get_status()
        if status.state == ProviderConnectionState.CONNECTED:
            return ProviderHealthStatus.ONLINE
        if status.state == ProviderConnectionState.NOT_INSTALLED:
            return ProviderHealthStatus.UNAVAILABLE
        return ProviderHealthStatus.UNKNOWN

    async def cancel(self, execution_id: str) -> None:
        event = self._cancel_events.get(execution_id)
        if event is not None:
            event.set()

    async def stream(self, request: AIRequest):  # noqa: ANN201 - AsyncIterator[str], see docstring
        """CLI adapters do not support incremental token streaming yet --
        `ShellRunner` reads a subprocess to completion rather than exposing
        it line-by-line. This yields the final content once, which is
        honest about the limitation instead of faking deltas."""
        response = await self.execute(request)
        yield response.content

    async def _run_cli(
        self,
        argv: list[str],
        *,
        cwd: Path | str | None,
        timeout: float,
        execution_id: str | None = None,
        stdin_data: bytes | None = None,
    ) -> RunResult:
        if self.binary_path() is None:
            raise ProviderUnavailableError(f"{self.binary_name!r} is not installed or not on PATH.")
        cancel_event = asyncio.Event()
        if execution_id is not None:
            self._cancel_events[execution_id] = cancel_event
        try:
            return await self._runner.run(
                argv, cwd=Path(cwd) if cwd else None, timeout=timeout, cancel_event=cancel_event,
                stdin_data=stdin_data,
            )
        except ToolDeniedError as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        finally:
            if execution_id is not None:
                self._cancel_events.pop(execution_id, None)


#: The `model_id` seeded into `ModelRegistry` for both CLI providers (see
#: `core/providers/registry.py`) -- a sentinel meaning "let the CLI use its
#: own configured/account default", never a real, passable model name. A
#: real bug, caught live: `routing.model` is always a non-empty string, so
#: naively doing `if requested_model:` before passing `-m`/`--model` also
#: forwards this sentinel itself as if it were a real model id, which the
#: CLI then rejects with a 400. `real_model_or_none` is the one place that
#: distinction is made -- every adapter must route through it, never
#: reimplement the check inline.
DEFAULT_MODEL_SENTINEL = "default"


def real_model_or_none(metadata: dict[str, object]) -> str | None:
    requested = metadata.get("model")
    if not requested or requested == DEFAULT_MODEL_SENTINEL:
        return None
    return str(requested)


def sandbox_mode_for(risk: RiskLevel) -> str:
    """Maps this app's own risk tiers onto the Codex CLI's native `-s`
    sandbox mode -- the mechanism that keeps a CLI-routed step from
    exceeding the autonomy the rest of the app enforces for that risk
    level, even though the CLI's own tool loop (not our Permission Engine)
    is what applies it. Never returns the "no sandbox at all" mode; that
    requires an explicit, separate user opt-in the router does not grant
    on its own.
    """
    if risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
        return "workspace-write"
    return "read-only"


def claude_permission_mode_for(risk: RiskLevel) -> str:
    """Same mapping, for the Claude Code CLI's `--permission-mode` --
    verified live: `acceptEdits` actually writes files non-interactively,
    `plan` genuinely makes no filesystem change (confirmed by running both
    against a real file-creation prompt). Always paired with
    `--permission-prompts none` by the caller, since a prompt Claude can't
    get an answer to in non-interactive mode would otherwise hang forever
    rather than fail closed.
    """
    if risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
        return "acceptEdits"
    return "plan"
