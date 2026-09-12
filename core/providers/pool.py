"""Provider pool: resolves a provider name to a configured `ProviderAdapter`.

This is the only place the rest of the orchestrator (Router, Executor)
touches to get an adapter instance -- it never imports `AnthropicProvider`
etc. directly. A provider only appears in the pool once its API key has
been configured (see `core.bridge.handlers` provider.set_credential), so
"is this provider usable at all" is simply "is it in the pool", while
`ProviderHealthMonitor` answers the finer-grained "is it *currently*
healthy" question.
"""

from __future__ import annotations

from core.providers.base import ProviderAdapter
from core.utils.errors import ProviderUnavailableError


class ProviderPool:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def unregister(self, name: str) -> None:
        self._adapters.pop(name, None)

    def get(self, name: str) -> ProviderAdapter:
        adapter = self._adapters.get(name)
        if adapter is None:
            raise ProviderUnavailableError(
                f"Provider '{name}' is not configured. Add its API key in Settings > Providers."
            )
        return adapter

    def is_registered(self, name: str) -> bool:
        return name in self._adapters

    def names(self) -> list[str]:
        return list(self._adapters.keys())
