"""Repository for the `sessions` table.

Deliberately thin: create/read/status-transition/list. The actual state
machine deciding *which* transitions are legal (e.g. can't resume a
CANCELLED session) belongs to `SessionManager` (Phase 2, the runtime
layer) -- this repository persists whatever status it is told, the same
division of responsibility `core.tasks.state_machine` already has relative
to `TasksRepository`.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.runtime.execution_backend import ExecutionBackendType
from core.sessions.models import TERMINAL_SESSION_STATUSES, Session, SessionCreate, SessionStatus
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_session(row: aiosqlite.Row) -> Session:
    return Session(
        id=row["id"],
        agent_id=row["agent_id"],
        project_id=row["project_id"],
        provider_id=row["provider_id"],
        runtime_binding_id=row["runtime_binding_id"],
        backend_type=ExecutionBackendType(row["backend_type"]),
        account_id=row["account_id"],
        task_id=row["task_id"],
        worktree_id=row["worktree_id"],
        external_session_id=row["external_session_id"],
        status=SessionStatus(row["status"]),
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        finished_at=row["finished_at"],
        metadata=loads(row["metadata"], {}),
        created_at=row["created_at"],
    )


class SessionsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, data: SessionCreate) -> Session:
        now = utc_now().isoformat()
        session_id = new_id("sess")
        await self._db.execute(
            """
            INSERT INTO sessions (id, agent_id, project_id, provider_id, backend_type, account_id,
                                   runtime_binding_id, task_id, worktree_id, external_session_id, status, started_at,
                                   updated_at, finished_at, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, NULL, ?, ?)
            """,
            (
                session_id, data.agent_id, data.project_id, data.provider_id, data.backend_type.value,
                data.account_id, data.runtime_binding_id, data.task_id, data.worktree_id, SessionStatus.CREATED.value, now,
                dumps(data.metadata), now,
            ),
        )
        created = await self.get(session_id)
        if created is None:
            raise RuntimeError("Session vanished immediately after creation.")
        return created

    async def get(self, session_id: str) -> Session | None:
        row = await self._db.fetch_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return _row_to_session(row) if row else None

    async def get_or_raise(self, session_id: str) -> Session:
        session = await self.get(session_id)
        if session is None:
            raise NotFoundError(f"Session '{session_id}' not found.")
        return session

    async def update_status(
        self, session_id: str, status: SessionStatus, *, started: bool = False, finished: bool = False,
    ) -> Session:
        current = await self.get_or_raise(session_id)
        now = utc_now().isoformat()
        started_at = (
            now if started and current.started_at is None
            else current.started_at.isoformat() if current.started_at else None
        )
        finished_at = now if finished else (current.finished_at.isoformat() if current.finished_at else None)
        await self._db.execute(
            "UPDATE sessions SET status = ?, started_at = ?, finished_at = ?, updated_at = ? WHERE id = ?",
            (status.value, started_at, finished_at, now, session_id),
        )
        return await self.get_or_raise(session_id)

    async def set_external_session_id(self, session_id: str, external_session_id: str) -> Session:
        await self.get_or_raise(session_id)
        now = utc_now().isoformat()
        await self._db.execute(
            "UPDATE sessions SET external_session_id = ?, updated_at = ? WHERE id = ?",
            (external_session_id, now, session_id),
        )
        return await self.get_or_raise(session_id)

    async def set_process(self, session_id: str, process_id: int | None, *, started: bool = False) -> Session:
        await self.get_or_raise(session_id)
        now = utc_now().isoformat()
        await self._db.execute(
            "UPDATE sessions SET process_id=?, process_started_at=COALESCE(process_started_at, ?), updated_at=? WHERE id=?",
            (str(process_id) if process_id is not None else None, now if started else None, now, session_id),
        )
        return await self.get_or_raise(session_id)

    async def assign_worktree(self, session_id: str, worktree_id: str) -> Session:
        await self.get_or_raise(session_id)
        now = utc_now().isoformat()
        await self._db.execute(
            "UPDATE sessions SET worktree_id = ?, updated_at = ? WHERE id = ?",
            (worktree_id, now, session_id),
        )
        return await self.get_or_raise(session_id)

    async def merge_metadata(self, session_id: str, patch: dict[str, Any]) -> Session:
        current = await self.get_or_raise(session_id)
        merged = {**current.metadata, **patch}
        now = utc_now().isoformat()
        await self._db.execute(
            "UPDATE sessions SET metadata = ?, updated_at = ? WHERE id = ?",
            (dumps(merged), now, session_id),
        )
        return await self.get_or_raise(session_id)

    async def list_by_agent(self, agent_id: str) -> list[Session]:
        rows = await self._db.fetch_all(
            "SELECT * FROM sessions WHERE agent_id = ? ORDER BY created_at DESC", (agent_id,)
        )
        return [_row_to_session(row) for row in rows]

    async def list_by_project(self, project_id: str) -> list[Session]:
        rows = await self._db.fetch_all(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
        )
        return [_row_to_session(row) for row in rows]

    async def list_active(self) -> list[Session]:
        active_values = [s.value for s in SessionStatus if s not in TERMINAL_SESSION_STATUSES]
        placeholders = ", ".join("?" for _ in active_values)
        rows = await self._db.fetch_all(
            f"SELECT * FROM sessions WHERE status IN ({placeholders}) ORDER BY created_at DESC",
            tuple(active_values),
        )
        return [_row_to_session(row) for row in rows]
