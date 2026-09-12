"""Repository for `context_metrics` -- how much context was sent to an
agent for one step, and which of it its output actually referenced. Feeds
`core.learning.context_optimizer.ContextOptimizer` (Layer: Context Learning).

"Effectively used" is a deterministic proxy, not a claim of causation: a
file counts as used if its path is mentioned in the step's own output
text. This is cheap and has no false positives (the model would not name a
file it never saw), though it can under-count silent influence.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["file_paths"] = loads(item["file_paths"], [])
    item["files_used"] = loads(item["files_used"], [])
    return item


class ContextMetricsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        execution_id: str,
        step_id: str,
        agent_id: str | None,
        file_paths: list[str],
        bytes_total: int,
        files_used: list[str],
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO context_metrics
                (id, execution_id, step_id, agent_id, files_count, bytes_total, file_paths,
                 files_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("ctxmetric"), execution_id, step_id, agent_id, len(file_paths), bytes_total,
                dumps(file_paths), dumps(files_used), utc_now().isoformat(),
            ),
        )

    async def list_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM context_metrics WHERE execution_id = ? ORDER BY created_at ASC",
            (execution_id,),
        )
        return [_row_to_dict(row) for row in rows]

    async def list_recent(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM context_metrics ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [_row_to_dict(row) for row in rows]
