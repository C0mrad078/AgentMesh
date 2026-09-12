"""ProviderManager: the discovery/status facade for CLI-based AI providers
(Codex CLI, Claude Code CLI, Gemini CLI) -- the "Tela de Providers" (§11)
and onboarding (§73) UI's single source of truth for "what's installed,
authenticated, and ready to route to".

Scope of this first version, stated honestly: HTTP-API providers
(Anthropic/Gemini/OpenAI) already have an equivalent concept --
`ProviderPool.is_registered()` + the `provider.health` bridge command --
this class does not duplicate that. It exists specifically for the three
CLI identities that had no discovery mechanism at all before now.
"""

from __future__ import annotations

import asyncio

from core.providers.base import ProviderStatus
from core.providers.claude_code_cli_provider import ClaudeCodeCliProvider
from core.providers.cli_provider import CliProviderAdapter
from core.providers.codex_cli_provider import CodexCliProvider
from core.providers.gemini_cli_provider import GeminiCliProvider

_CLI_PROVIDER_FACTORIES: dict[str, type[CliProviderAdapter]] = {
    "codex_cli": CodexCliProvider,
    "claude_code_cli": ClaudeCodeCliProvider,
    "gemini_cli": GeminiCliProvider,
}


class ProviderManager:
    """Owns one long-lived instance of each CLI adapter (so their internal
    `_cancel_events` bookkeeping is shared across calls) and answers
    discovery/status queries against them. Never caches a status result --
    every call re-runs the real diagnostic, since "was connected 5 minutes
    ago" is not the question the UI is asking.
    """

    def __init__(self) -> None:
        self._cli_adapters = {name: factory() for name, factory in _CLI_PROVIDER_FACTORIES.items()}

    def cli_provider_names(self) -> list[str]:
        return list(self._cli_adapters.keys())

    def cli_adapter(self, name: str) -> CliProviderAdapter:
        adapter = self._cli_adapters.get(name)
        if adapter is None:
            raise KeyError(f"Unknown CLI provider {name!r}. Known: {self.cli_provider_names()}")
        return adapter

    async def cli_status(self, name: str) -> ProviderStatus:
        return await self.cli_adapter(name).get_status()

    async def list_cli_statuses(self) -> dict[str, ProviderStatus]:
        names = self.cli_provider_names()
        statuses = await asyncio.gather(*(self.cli_status(name) for name in names))
        return dict(zip(names, statuses, strict=True))
