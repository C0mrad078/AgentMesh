"""Repository for `messages`. Backing store for the future chat area."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


class MessagesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        message_id = new_id("msg")
        now = utc_now().isoformat()
        await self._db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, conversation_id, role, content, dumps(metadata or {}), now),
        )
        row = await self._db.fetch_one("SELECT * FROM messages WHERE id = ?", (message_id,))
        assert row is not None
        result = dict(row)
        result["metadata"] = loads(result["metadata"], {})
        return result

    async def list_for_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        )
        results = []
        for row in rows:
            item = dict(row)
            item["metadata"] = loads(item["metadata"], {})
            results.append(item)
        return results
