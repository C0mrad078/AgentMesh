"""Repository for the `project_memories` table.

A key's *history* is append-only: `create_active` always inserts a new row,
and a partial unique index (`project_id, key` WHERE `valid_until IS NULL`,
see migration 0004) guarantees at most one currently-valid row per key --
`supersede()` must be called on the previous active row (in the same
transaction as the new insert) before a second `create_active` for the
same key would otherwise violate it. This is what lets
`core.memory.store.SqliteMemoryStore.remember` detect and record a
conflict instead of silently overwriting a fact in place.
"""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.memory.models import (
    MemoryCategory,
    MemoryKind,
    MemoryProvenance,
    MemoryRecord,
    MemoryScope,
    MemoryWrite,
)
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_record(row: aiosqlite.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        scope=MemoryScope(row["scope"]),
        project_id=row["project_id"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        kind=MemoryKind(row["kind"]),
        category=MemoryCategory(row["category"]),
        key=row["key"],
        value=loads(row["value"], {}),
        importance=row["importance"],
        confidence=row["confidence"],
        provenance=MemoryProvenance(**loads(row["provenance"], {})),
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        superseded_by=row["superseded_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ProjectMemoriesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_active(self, data: MemoryWrite, *, memory_id: str | None = None) -> MemoryRecord:
        now = utc_now().isoformat()
        memory_id = memory_id or new_id("mem")
        await self._db.execute(
            """
            INSERT INTO project_memories
                (id, scope, project_id, agent_id, session_id, kind, category, key, value,
                 importance, confidence, provenance, valid_from, valid_until, superseded_by,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                memory_id, data.scope.value, data.project_id, data.agent_id, data.session_id,
                data.kind.value, data.category.value, data.key,
                dumps(data.value), data.importance, data.confidence,
                dumps(data.provenance.model_dump()), now, now, now,
            ),
        )
        row = await self._db.fetch_one("SELECT * FROM project_memories WHERE id = ?", (memory_id,))
        assert row is not None
        return _row_to_record(row)

    async def supersede(self, memory_id: str, *, superseded_by: str) -> None:
        await self._db.execute(
            "UPDATE project_memories SET valid_until = ?, superseded_by = ?, updated_at = ? WHERE id = ?",
            (utc_now().isoformat(), superseded_by, utc_now().isoformat(), memory_id),
        )

    async def touch(self, memory_id: str, *, confidence: float) -> MemoryRecord:
        """A re-observation of an identical value -- refresh confidence and
        `updated_at` without creating a new row or a conflict."""
        await self._db.execute(
            "UPDATE project_memories SET confidence = ?, updated_at = ? WHERE id = ?",
            (confidence, utc_now().isoformat(), memory_id),
        )
        row = await self._db.fetch_one("SELECT * FROM project_memories WHERE id = ?", (memory_id,))
        assert row is not None
        return _row_to_record(row)

    async def get_active(self, project_id: str, key: str) -> MemoryRecord | None:
        row = await self._db.fetch_one(
            "SELECT * FROM project_memories WHERE project_id = ? AND key = ? AND valid_until IS NULL",
            (project_id, key),
        )
        return _row_to_record(row) if row else None

    async def get_active_for_scope(self, data: MemoryWrite) -> MemoryRecord | None:
        """Scope-generic counterpart of `get_active` -- the column checked
        against `key` depends on `data.scope` (enforced by `MemoryWrite`'s
        own validator, so exactly one of these is ever non-None)."""
        column = {
            MemoryScope.PROJECT: ("project_id", data.project_id),
            MemoryScope.AGENT: ("agent_id", data.agent_id),
            MemoryScope.SESSION: ("session_id", data.session_id),
        }.get(data.scope)
        if column is None:  # GLOBAL -- no owning column, just scope + key
            row = await self._db.fetch_one(
                "SELECT * FROM project_memories WHERE scope = 'global' AND key = ? AND valid_until IS NULL",
                (data.key,),
            )
        else:
            column_name, value = column
            row = await self._db.fetch_one(
                f"SELECT * FROM project_memories WHERE {column_name} = ? AND key = ? "
                "AND valid_until IS NULL",
                (value, data.key),
            )
        return _row_to_record(row) if row else None

    async def list_active_for_scope(
        self, scope: MemoryScope, *, project_id: str | None = None,
        agent_id: str | None = None, session_id: str | None = None,
    ) -> list[MemoryRecord]:
        column = {
            MemoryScope.PROJECT: ("project_id", project_id),
            MemoryScope.AGENT: ("agent_id", agent_id),
            MemoryScope.SESSION: ("session_id", session_id),
        }.get(scope)
        if column is None:
            rows = await self._db.fetch_all(
                "SELECT * FROM project_memories WHERE scope = 'global' AND valid_until IS NULL "
                "ORDER BY importance DESC",
            )
        else:
            column_name, value = column
            rows = await self._db.fetch_all(
                f"SELECT * FROM project_memories WHERE {column_name} = ? AND valid_until IS NULL "
                "ORDER BY importance DESC",
                (value,),
            )
        return [_row_to_record(row) for row in rows]

    async def list_active_for_project(self, project_id: str) -> list[MemoryRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM project_memories WHERE project_id = ? AND valid_until IS NULL "
            "ORDER BY importance DESC",
            (project_id,),
        )
        return [_row_to_record(row) for row in rows]

    async def list_history_for_key(self, project_id: str, key: str) -> list[MemoryRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM project_memories WHERE project_id = ? AND key = ? ORDER BY created_at DESC",
            (project_id, key),
        )
        return [_row_to_record(row) for row in rows]

    # -- Stage 1/2 compatibility -----------------------------------------
    # `upsert`/`get`/`list_for_project` are the pre-Stage-3 names; kept so
    # nothing outside `core.memory` needs to change, mapped onto the new
    # supersession-aware storage.

    async def get(self, project_id: str, key: str) -> MemoryRecord | None:
        return await self.get_active(project_id, key)

    async def list_for_project(self, project_id: str) -> list[MemoryRecord]:
        return await self.list_active_for_project(project_id)
