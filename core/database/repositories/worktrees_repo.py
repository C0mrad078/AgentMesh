"""Repository for the `worktrees` table."""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now
from core.worktrees.models import Worktree, WorktreeCreate, WorktreeStatus


def _row_to_worktree(row: aiosqlite.Row) -> Worktree:
    return Worktree(
        id=row["id"],
        project_id=row["project_id"],
        branch_name=row["branch_name"],
        path=row["path"],
        status=WorktreeStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        removed_at=row["removed_at"],
    )


class WorktreesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, data: WorktreeCreate) -> Worktree:
        now = utc_now().isoformat()
        worktree_id = new_id("wt")
        await self._db.execute(
            """
            INSERT INTO worktrees (id, project_id, branch_name, path, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (worktree_id, data.project_id, data.branch_name, data.path, WorktreeStatus.ACTIVE.value, now, now),
        )
        created = await self.get(worktree_id)
        if created is None:
            raise RuntimeError("Worktree vanished immediately after creation.")
        return created

    async def get(self, worktree_id: str) -> Worktree | None:
        row = await self._db.fetch_one("SELECT * FROM worktrees WHERE id = ?", (worktree_id,))
        return _row_to_worktree(row) if row else None

    async def get_or_raise(self, worktree_id: str) -> Worktree:
        worktree = await self.get(worktree_id)
        if worktree is None:
            raise NotFoundError(f"Worktree '{worktree_id}' not found.")
        return worktree

    async def list_by_project(self, project_id: str, *, only_active: bool = True) -> list[Worktree]:
        if only_active:
            rows = await self._db.fetch_all(
                "SELECT * FROM worktrees WHERE project_id = ? AND status = ? ORDER BY created_at",
                (project_id, WorktreeStatus.ACTIVE.value),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM worktrees WHERE project_id = ? ORDER BY created_at", (project_id,)
            )
        return [_row_to_worktree(row) for row in rows]

    async def mark_status(self, worktree_id: str, status: WorktreeStatus) -> Worktree:
        await self.get_or_raise(worktree_id)
        now = utc_now().isoformat()
        removed_at = now if status == WorktreeStatus.CLEANED else None
        await self._db.execute(
            "UPDATE worktrees SET status = ?, removed_at = ?, updated_at = ? WHERE id = ?",
            (status.value, removed_at, now, worktree_id),
        )
        return await self.get_or_raise(worktree_id)
