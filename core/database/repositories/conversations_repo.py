"""Repository for `conversations`. Backing store for the future chat area."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.utils.ids import new_id
from core.utils.time import utc_now


class ConversationsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, project_id: str, title: str = "") -> dict[str, Any]:
        conversation_id = new_id("conv")
        now = utc_now().isoformat()
        await self._db.execute(
            "INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, project_id, title, now, now),
        )
        row = await self._db.fetch_one(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        )
        assert row is not None
        return dict(row)

    async def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        )
        return [dict(row) for row in rows]
