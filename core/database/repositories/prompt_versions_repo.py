"""Repository for the `prompt_versions` table.

Each agent has at most one *active* prompt version at a time. Creating a
new version for an agent deactivates the previous one (in the same
transaction) rather than deleting it -- history is kept so Stage 3 can
correlate execution outcomes with which prompt version was live at the
time, and so a prompt can be rolled back.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["metadata"] = loads(item["metadata"], {})
    item["active"] = bool(item["active"])
    return item


class PromptVersionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_active(self, agent_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM prompt_versions WHERE agent_id = ? AND active = 1 "
            "ORDER BY version DESC LIMIT 1",
            (agent_id,),
        )
        return _row_to_dict(row) if row else None

    async def list_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM prompt_versions WHERE agent_id = ? ORDER BY version DESC",
            (agent_id,),
        )
        return [_row_to_dict(row) for row in rows]

    async def create_version(
        self, agent_id: str, name: str, content: str, *, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        current = await self.get_active(agent_id)
        next_version = (current["version"] + 1) if current else 1

        async with self._db.transaction() as conn:
            if current:
                await conn.execute(
                    "UPDATE prompt_versions SET active = 0 WHERE id = ?", (current["id"],)
                )
            prompt_id = new_id("prompt")
            await conn.execute(
                """
                INSERT INTO prompt_versions (id, agent_id, name, version, content, metadata,
                                              created_at, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    prompt_id, agent_id, name, next_version, content,
                    dumps(metadata or {}), utc_now().isoformat(),
                ),
            )

        row = await self._db.fetch_one("SELECT * FROM prompt_versions WHERE id = ?", (prompt_id,))
        assert row is not None
        return _row_to_dict(row)

    async def seed_default(self, agent_id: str, name: str, content: str) -> None:
        """Create the initial version for an agent only if it has none yet."""
        existing = await self.get_active(agent_id)
        if existing is not None:
            return
        await self.create_version(agent_id, name, content)
