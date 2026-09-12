"""Repository for the `execution_events` table -- the persisted half of
`core.orchestrator.event_bus.EventBus` (the other half is the live
`orchestrator://event` stream to the frontend). Backs the history/debug
view ("Execution Inspector")."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.orchestrator.event_bus import OrchestrationEvent
from core.utils.ids import new_id


class ExecutionEventsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, event: OrchestrationEvent) -> None:
        await self._db.execute(
            """
            INSERT INTO execution_events (id, execution_id, task_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("evt"), event.execution_id, event.task_id, event.type.value,
                dumps(event.payload), event.timestamp,
            ),
        )

    async def list_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM execution_events WHERE execution_id = ? ORDER BY created_at ASC",
            (execution_id,),
        )
        results = []
        for row in rows:
            item = dict(row)
            item["payload"] = loads(item["payload"], {})
            results.append(item)
        return results
