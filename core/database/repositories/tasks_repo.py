"""Repository for the `tasks` table."""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.tasks.models import Task, TaskCreate, TaskMode, TaskStatus
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_task(row: aiosqlite.Row) -> Task:
    return Task(
        id=row["id"],
        project_id=row["project_id"],
        conversation_id=row["conversation_id"],
        title=row["title"],
        description=row["description"],
        mode=TaskMode(row["mode"]),
        status=TaskStatus(row["status"]),
        input=loads(row["input"], {}),
        result=loads(row["result"], None) if row["result"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


class TasksRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, data: TaskCreate) -> Task:
        now = utc_now()
        task_id = new_id("task")
        await self._db.execute(
            """
            INSERT INTO tasks (id, project_id, conversation_id, title, description, mode,
                                status, input, result, created_at, updated_at, started_at,
                                completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL)
            """,
            (
                task_id,
                data.project_id,
                data.conversation_id,
                data.title,
                data.description,
                data.mode.value,
                TaskStatus.QUEUED.value,
                dumps(data.input),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        return await self.get_or_raise(task_id)

    async def get(self, task_id: str) -> Task | None:
        row = await self._db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _row_to_task(row) if row else None

    async def get_or_raise(self, task_id: str) -> Task:
        task = await self.get(task_id)
        if task is None:
            raise NotFoundError(f"Task '{task_id}' not found.")
        return task

    async def list_for_project(self, project_id: str) -> list[Task]:
        rows = await self._db.fetch_all(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
        return [_row_to_task(row) for row in rows]

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        result: dict | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> Task:
        current = await self.get_or_raise(task_id)
        now = utc_now().isoformat()
        await self._db.execute(
            """
            UPDATE tasks
            SET status = ?, result = COALESCE(?, result), updated_at = ?,
                started_at = COALESCE(?, started_at),
                completed_at = COALESCE(?, completed_at)
            WHERE id = ?
            """,
            (
                status.value,
                dumps(result) if result is not None else None,
                now,
                started_at,
                completed_at,
                task_id,
            ),
        )
        _ = current
        return await self.get_or_raise(task_id)

    async def find_stale_running(self) -> list[Task]:
        """Tasks left in a non-terminal in-flight state, used by crash recovery."""
        rows = await self._db.fetch_all(
            "SELECT * FROM tasks WHERE status IN (?, ?, ?)",
            (TaskStatus.RUNNING.value, TaskStatus.WAITING.value, TaskStatus.REVIEWING.value),
        )
        return [_row_to_task(row) for row in rows]
