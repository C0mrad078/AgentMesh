"""Repository for the `audit_logs` table."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps
from core.utils.ids import new_id
from core.utils.time import utc_now


class AuditLogsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        *,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        context: dict[str, Any],
    ) -> str:
        entry_id = new_id("audit")
        await self._db.execute(
            """
            INSERT INTO audit_logs (id, actor, action, resource_type, resource_id, context,
                                     created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_id, actor, action, resource_type, resource_id, dumps(context), utc_now().isoformat()),
        )
        return entry_id

    async def list_for_resource(self, resource_type: str, resource_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM audit_logs
            WHERE resource_type = ? AND resource_id = ?
            ORDER BY created_at DESC
            """,
            (resource_type, resource_id),
        )
        return [dict(row) for row in rows]
