from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from core.utils.errors import ValidationError


@dataclass(frozen=True)
class ParallelLimits:
    global_sessions: int = 4
    per_provider: int = 2
    per_binding: int = 4
    per_project: int = 3
    per_mission: int = 3


class ParallelConcurrency:
    """Persisted admission is done by the repository; semaphores protect one process."""

    def __init__(self, limits: ParallelLimits | None = None) -> None:
        self.limits = limits or ParallelLimits()
        self._global = asyncio.Semaphore(self.limits.global_sessions)
        self._provider: dict[str, asyncio.Semaphore] = {}
        self._binding: dict[str, asyncio.Semaphore] = {}
        self._project: dict[str, asyncio.Semaphore] = {}
        self._mission: dict[str, asyncio.Semaphore] = {}

    def _get(self, values: dict[str, asyncio.Semaphore], key: str, limit: int) -> asyncio.Semaphore:
        if key not in values:
            values[key] = asyncio.Semaphore(limit)
        return values[key]

    @asynccontextmanager
    async def acquire(self, *, provider: str, project_id: str, mission_id: str, binding_id: str | None = None) -> AsyncIterator[None]:
        async with self._global:
            async with self._get(self._provider, provider, self.limits.per_provider):
                if binding_id:
                    async with self._get(self._binding, binding_id, self.limits.per_binding):
                        async with self._get(self._project, project_id, self.limits.per_project):
                            async with self._get(self._mission, mission_id, self.limits.per_mission):
                                yield
                else:
                    async with self._get(self._project, project_id, self.limits.per_project):
                        async with self._get(self._mission, mission_id, self.limits.per_mission):
                            yield

    def validate(self) -> None:
        if min(self.limits.global_sessions, self.limits.per_provider, self.limits.per_binding,
               self.limits.per_project, self.limits.per_mission) < 1:
            raise ValidationError("Todos os limites de concorrência precisam ser positivos.")
