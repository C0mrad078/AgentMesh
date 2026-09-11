"""Repository for the `executions` table."""

from __future__ import annotations

from typing import Any

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.orchestrator.models import ExecutionStatus
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now


class ExecutionRecord:
    def __init__(self, row: aiosqlite.Row) -> None:
        self.id: str = row["id"]
        self.task_id: str = row["task_id"]
        self.project_id: str = row["project_id"]
        self.status = ExecutionStatus(row["status"])
        self.plan: dict[str, Any] = loads(row["plan"], {})
        self.current_step_index: int = row["current_step_index"]
        self.attempt: int = row["attempt"]
        self.error: dict[str, Any] | None = loads(row["error"], None) if row["error"] else None
        self.started_at: str | None = row["started_at"]
        self.completed_at: str | None = row["completed_at"]
        self.created_at: str = row["created_at"]
        self.updated_at: str = row["updated_at"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "plan": self.plan,
            "current_step_index": self.current_step_index,
            "attempt": self.attempt,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ExecutionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, *, task_id: str, project_id: str) -> ExecutionRecord:
        now = utc_now().isoformat()
        execution_id = new_id("exec")
        await self._db.execute(
            """
            INSERT INTO executions (id, task_id, project_id, status, plan, current_step_index,
                                     attempt, error, started_at, completed_at, created_at,
                                     updated_at)
            VALUES (?, ?, ?, ?, '{}', 0, 1, NULL, ?, NULL, ?, ?)
            """,
            (execution_id, task_id, project_id, ExecutionStatus.RUNNING.value, now, now, now),
        )
        return await self.get_or_raise(execution_id)

    async def get(self, execution_id: str) -> ExecutionRecord | None:
        row = await self._db.fetch_one("SELECT * FROM executions WHERE id = ?", (execution_id,))
        return ExecutionRecord(row) if row else None

    async def get_or_raise(self, execution_id: str) -> ExecutionRecord:
        record = await self.get(execution_id)
        if record is None:
            raise NotFoundError(f"Execution '{execution_id}' not found.")
        return record

    async def list_for_project(self, project_id: str) -> list[ExecutionRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM executions WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
        return [ExecutionRecord(row) for row in rows]

    async def update_plan(self, execution_id: str, plan: dict[str, Any]) -> None:
        await self._db.execute(
            "UPDATE executions SET plan = ?, updated_at = ? WHERE id = ?",
            (dumps(plan), utc_now().isoformat(), execution_id),
        )

    async def update_status(
        self,
        execution_id: str,
        status: ExecutionStatus,
        *,
        error: dict[str, Any] | None = None,
        completed: bool = False,
    ) -> None:
        now = utc_now().isoformat()
        await self._db.execute(
            """
            UPDATE executions
            SET status = ?, error = COALESCE(?, error), updated_at = ?,
                completed_at = CASE WHEN ? THEN ? ELSE completed_at END
            WHERE id = ?
            """,
            (status.value, dumps(error) if error else None, now, completed, now, execution_id),
        )

    async def find_stale_running(self) -> list[ExecutionRecord]:
        rows = await self._db.fetch_all(
            "SELECT * FROM executions WHERE status = ?", (ExecutionStatus.RUNNING.value,)
        )
        return [ExecutionRecord(row) for row in rows]
