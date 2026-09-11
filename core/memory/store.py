"""Memory store contract and its SQLite-backed implementation.

`MemoryStore` is the interface the rest of the orchestrator programs
against; `SqliteMemoryStore` is Stage 1's only implementation. Keeping the
contract separate from the backing store means a future in-process vector
index or external memory service can be introduced by adding a new
implementation, not by changing every call site.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.database.repositories.project_memories_repo import ProjectMemoriesRepository
from core.memory.models import MemoryRecord, MemoryWrite


class MemoryStore(ABC):
    @abstractmethod
    async def remember(self, data: MemoryWrite) -> MemoryRecord: ...

    @abstractmethod
    async def recall(self, project_id: str, key: str) -> MemoryRecord | None: ...

    @abstractmethod
    async def recall_all(self, project_id: str) -> list[MemoryRecord]: ...


class SqliteMemoryStore(MemoryStore):
    def __init__(self, repository: ProjectMemoriesRepository) -> None:
        self._repository = repository

    async def remember(self, data: MemoryWrite) -> MemoryRecord:
        return await self._repository.upsert(data)

    async def recall(self, project_id: str, key: str) -> MemoryRecord | None:
        return await self._repository.get(project_id, key)

    async def recall_all(self, project_id: str) -> list[MemoryRecord]:
        return await self._repository.list_for_project(project_id)
