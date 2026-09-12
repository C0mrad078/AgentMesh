"""Concurrency limits for provider calls.

The DAG executor can run independent plan steps in parallel, but that must
never translate into dozens of simultaneous requests hitting a provider (or
the app in general). `ConcurrencyManager` hands out semaphore-backed permits
scoped by provider, by model, and globally, so:

  * a single provider can't be overwhelmed even if many steps route to it
    at once;
  * a single (provider, model) pair has its own, usually tighter, limit
    (cheap/fast models can tolerate more parallel calls than an expensive
    flagship one);
  * there is always a hard ceiling on total simultaneous provider calls
    regardless of how they're distributed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConcurrencyLimits:
    global_max: int = 8
    per_provider_max: int = 4
    per_model_max: int = 2


@dataclass
class _Semaphores:
    global_sem: asyncio.Semaphore
    provider: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    model: dict[str, asyncio.Semaphore] = field(default_factory=dict)


class ConcurrencyManager:
    def __init__(self, limits: ConcurrencyLimits | None = None) -> None:
        self._limits = limits or ConcurrencyLimits()
        self._sems = _Semaphores(global_sem=asyncio.Semaphore(self._limits.global_max))

    def _provider_sem(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._sems.provider:
            self._sems.provider[provider] = asyncio.Semaphore(self._limits.per_provider_max)
        return self._sems.provider[provider]

    def _model_sem(self, provider: str, model: str) -> asyncio.Semaphore:
        key = f"{provider}:{model}"
        if key not in self._sems.model:
            self._sems.model[key] = asyncio.Semaphore(self._limits.per_model_max)
        return self._sems.model[key]

    @asynccontextmanager
    async def acquire(self, provider: str, model: str) -> AsyncIterator[None]:
        """Acquire global + provider + model permits, in a fixed order, to
        avoid deadlocking against another call acquiring the same three
        semaphores in a different order.
        """
        async with self._sems.global_sem:
            async with self._provider_sem(provider):
                async with self._model_sem(provider, model):
                    yield
