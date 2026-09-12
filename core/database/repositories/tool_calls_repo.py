"""Repository for the `tool_calls` table -- an audit trail of every tool a
step actually invoked, its arguments, and its outcome."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.ids import new_id
from core.utils.time import utc_now


class ToolCallsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        execution_id: str,
        step_id: str | None,
        agent_id: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any = None,
        error: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO tool_calls
                (id, execution_id, step_id, agent_id, tool_name, arguments, result, error,
                 duration_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("toolcall"), execution_id, step_id, agent_id, tool_name,
                dumps(arguments), dumps(result) if result is not None else None, error,
                duration_seconds, utc_now().isoformat(),
            ),
        )

    async def list_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM tool_calls WHERE execution_id = ? ORDER BY created_at ASC",
            (execution_id,),
        )
        results = []
        for row in rows:
            item = dict(row)
            item["arguments"] = loads(item["arguments"], {})
            item["result"] = loads(item["result"], None) if item["result"] else None
            results.append(item)
        return results
