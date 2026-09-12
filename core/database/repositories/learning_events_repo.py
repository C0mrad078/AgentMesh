"""Repository for `learning_events` -- the auditability trail every Stage 3
mutation must leave behind: what changed, when, why, by whom, from what
previous state. Every write the Learning Engine, Prompt Optimizer, or a
user learning action performs is logged here, in addition to whatever
domain table it also updates.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["evidence"] = loads(item["evidence"], {})
    if item.get("previous_state") is not None:
        item["previous_state"] = loads(item["previous_state"], None)
    return item


class LearningEventsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        event_type: str,
        target_type: str,
        target_id: str,
        actor: str = "learning_engine",
        evidence: dict[str, Any] | None = None,
        previous_state: dict[str, Any] | None = None,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO learning_events
                (id, event_type, target_type, target_id, actor, evidence, previous_state, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("learnevt"), event_type, target_type, target_id, actor,
                dumps(evidence or {}), dumps(previous_state) if previous_state is not None else None,
                utc_now().isoformat(),
            ),
        )

    async def count_activations_since(self, since_iso: str) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) as n FROM learning_events "
            "WHERE actor = 'learning_engine' AND event_type LIKE '%_activated' AND created_at >= ?",
            (since_iso,),
        )
        return int(row["n"]) if row else 0

    async def list_for_target(self, target_type: str, target_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM learning_events WHERE target_type = ? AND target_id = ? "
            "ORDER BY created_at DESC",
            (target_type, target_id),
        )
        return [_row_to_dict(row) for row in rows]

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM learning_events ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [_row_to_dict(row) for row in rows]
