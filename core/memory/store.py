"""Memory store contract and its SQLite-backed implementation.

`MemoryStore` is the interface the rest of the orchestrator programs
against; `SqliteMemoryStore` is the only implementation. `remember()`
implements Stage 3's conflict handling: a new value for an existing key is
never written in place over the old one -- the old row is marked
superseded (`valid_until`/`superseded_by`) and a `memory_conflicts` row
records that it happened, while the new row becomes the sole currently
"active" fact for that key (enforced by a partial unique index -- see
`core.database.repositories.project_memories_repo`). Re-observing an
*identical* value is not a conflict: it only refreshes the existing row's
confidence/timestamp.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.database.repositories.memory_conflicts_repo import MemoryConflictsRepository
from core.database.repositories.project_memories_repo import ProjectMemoriesRepository
from core.memory.models import MemoryRecord, MemoryWrite
from core.utils.ids import new_id


class MemoryStore(ABC):
    @abstractmethod
    async def remember(self, data: MemoryWrite) -> MemoryRecord: ...

    @abstractmethod
    async def recall(self, project_id: str, key: str) -> MemoryRecord | None: ...

    @abstractmethod
    async def recall_all(self, project_id: str) -> list[MemoryRecord]: ...


class SqliteMemoryStore(MemoryStore):
    def __init__(
        self, repository: ProjectMemoriesRepository, conflicts_repo: MemoryConflictsRepository | None = None,
    ) -> None:
        self._repository = repository
        self._conflicts = conflicts_repo

    async def remember(self, data: MemoryWrite) -> MemoryRecord:
        # User-supplied facts are treated differently from inferred ones:
        # an explicit statement from the user is never less than fully
        # confident, regardless of what the caller passed.
        if data.provenance.source_user_input and data.confidence < 1.0:
            data = data.model_copy(update={"confidence": 1.0})

        existing = await self._repository.get_active(data.project_id, data.key)
        if existing is not None and existing.value == data.value:
            return await self._repository.touch(existing.id, confidence=max(existing.confidence, data.confidence))

        new_memory_id = new_id("mem")
        if existing is not None:
            # Supersede the old row *before* inserting the new one -- both
            # cannot be "active" for the same key at once under the
            # partial unique index (see migration 0004).
            await self._repository.supersede(existing.id, superseded_by=new_memory_id)
        new_record = await self._repository.create_active(data, memory_id=new_memory_id)
        if existing is not None and self._conflicts is not None:
            await self._conflicts.record(
                data.project_id, old_memory_id=existing.id, new_memory_id=new_record.id,
                detail=f"Chave '{data.key}' atualizada: valor anterior substituído.",
            )
        return new_record

    async def recall(self, project_id: str, key: str) -> MemoryRecord | None:
        return await self._repository.get_active(project_id, key)

    async def recall_all(self, project_id: str) -> list[MemoryRecord]:
        return await self._repository.list_active_for_project(project_id)

    async def history(self, project_id: str, key: str) -> list[MemoryRecord]:
        return await self._repository.list_history_for_key(project_id, key)
