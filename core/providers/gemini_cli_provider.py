"""Gemini CLI provider: wraps the official `gemini` CLI.

Unlike `CodexCliProvider`/`ClaudeCodeCliProvider`, this adapter's `execute()`
is **not** verified against a real installation -- the Gemini CLI is not
installed in this development environment, and this project's own policy
(see `docs/BUILD.md`, `docs/RELEASE.md`) is to never present unverified
behavior as tested. `get_status()` is safe to ship: it only ever checks
binary presence and reports `NOT_INSTALLED` truthfully, which is exactly
the state this environment can actually confirm (verified: `shutil.which
("gemini")` returns `None` here). `execute()` raises a clear, honest error
instead of guessing at flags that could silently misbehave.

To finish this adapter for real: install the Gemini CLI, capture its
actual `--output-format json`-equivalent event schema the same way
`core.providers.codex_events`/`core.providers.claude_events` were built
(real invocations, not documentation), then implement `execute()` the same
way. Do not skip that step and ship guessed flags as if verified.
"""

from __future__ import annotations

from core.providers.base import AIRequest, AIResponse, ProviderConnectionState, ProviderStatus
from core.providers.cli_provider import CliProviderAdapter
from core.utils.errors import ProviderUnavailableError


class GeminiCliProvider(CliProviderAdapter):
    name = "gemini_cli"
    binary_name = "gemini"

    async def get_status(self) -> ProviderStatus:
        if self.binary_path() is None:
            return ProviderStatus(
                access_method=self.access_method, state=ProviderConnectionState.NOT_INSTALLED,
                detail="`gemini` was not found on PATH. Install the official Gemini CLI, "
                       "then restart the Orquestrador.",
            )
        version_result = await self._run_cli(["gemini", "--version"], cwd=None, timeout=10.0)
        # Login-state detection is intentionally not implemented here (see
        # module docstring): reporting a fabricated auth state would be
        # worse than reporting "installed, but this app cannot yet confirm
        # whether it's logged in."
        return ProviderStatus(
            access_method=self.access_method, state=ProviderConnectionState.DISCONNECTED,
            version=version_result.stdout.strip() or None,
            detail="Gemini CLI execution is not yet implemented in this build "
                   "(never verified against a real installation) -- see the module docstring.",
        )

    async def execute(self, request: AIRequest) -> AIResponse:
        raise ProviderUnavailableError(
            "Gemini CLI execution is not implemented yet -- it has never been verified "
            "against a real installation. See core/providers/gemini_cli_provider.py."
        )

    async def list_models(self) -> list[str]:
        return []
