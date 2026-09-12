"""Repository for `memory_conflicts` -- recorded whenever a new project
memory fact supersedes an older, contradictory one (see
`core.memory.store.SqliteMemoryStore.remember`, which detects the conflict;
this repository only records that it happened, for auditability)."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.utils.ids import new_id
from core.utils.time import utc_now


class MemoryConflictsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self, project_id: str, *, old_memory_id: str, new_memory_id: str, detail: str,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO memory_conflicts (id, project_id, old_memory_id, new_memory_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id("conflict"), project_id, old_memory_id, new_memory_id, detail, utc_now().isoformat()),
        )

    async def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM memory_conflicts WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
        return [dict(row) for row in rows]
