"""Repository for the `project_memories` table."""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.memory.models import MemoryKind, MemoryRecord, MemoryWrite
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_record(row: aiosqlite.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        project_id=row["project_id"],
        kind=MemoryKind(row["kind"]),
        key=row["key"],
        value=loads(row["value"], {}),
        importance=row["importance"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ProjectMemoriesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, data: MemoryWrite) -> MemoryRecord:
        """Insert or update the memory identified by `(project_id, key)`.

        Uses a single atomic `INSERT ... ON CONFLICT DO UPDATE` (backed by
        the unique index from migration 0002) instead of a
        select-then-branch, which would otherwise race under concurrent
        calls for the same key and could produce duplicate rows.
        """
        now = utc_now().isoformat()
        memory_id = new_id("mem")
        await self._db.execute(
            """
            INSERT INTO project_memories (id, project_id, kind, key, value, importance,
                                            created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, key) DO UPDATE SET
                value = excluded.value,
                importance = excluded.importance,
                kind = excluded.kind,
                updated_at = excluded.updated_at
            """,
            (
                memory_id, data.project_id, data.kind.value, data.key, dumps(data.value),
                data.importance, now, now,
            ),
        )
        row = await self._db.fetch_one(
            "SELECT * FROM project_memories WHERE project_id = ? AND key = ?",
            (data.project_id, data.key),
        )
        assert row is not None
        return _row_to_record(row)

    async def list_for_project(self, project_id: str) -> list[MemoryRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM project_memories WHERE project_id = ? ORDER BY importance DESC",
            (project_id,),
        )
        return [_row_to_record(row) for row in rows]

    async def get(self, project_id: str, key: str) -> MemoryRecord | None:
        row = await self._db.fetch_one(
            "SELECT * FROM project_memories WHERE project_id = ? AND key = ?",
            (project_id, key),
        )
        return _row_to_record(row) if row else None
