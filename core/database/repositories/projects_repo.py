"""Repository for the `projects` table. All project SQL lives here."""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.projects.models import Project, ProjectCreate, ProjectStatus, ProjectUpdate
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_project(row: aiosqlite.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        workspace_path=row["workspace_path"],
        status=ProjectStatus(row["status"]),
        config=loads(row["config"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ProjectsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, data: ProjectCreate) -> Project:
        now = utc_now()
        project_id = new_id("proj")
        await self._db.execute(
            """
            INSERT INTO projects (id, name, description, workspace_path, status, config,
                                   created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                data.name,
                data.description,
                data.workspace_path,
                ProjectStatus.ACTIVE.value,
                dumps(data.config),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        created = await self.get(project_id)
        if created is None:
            raise RuntimeError("Project vanished immediately after creation.")
        return created

    async def get(self, project_id: str) -> Project | None:
        row = await self._db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        return _row_to_project(row) if row else None

    async def get_or_raise(self, project_id: str) -> Project:
        project = await self.get(project_id)
        if project is None:
            raise NotFoundError(f"Project '{project_id}' not found.")
        return project

    async def list(self, *, include_archived: bool = False) -> list[Project]:
        if include_archived:
            rows = await self._db.fetch_all("SELECT * FROM projects ORDER BY updated_at DESC")
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC",
                (ProjectStatus.ACTIVE.value,),
            )
        return [_row_to_project(row) for row in rows]

    async def update(self, project_id: str, data: ProjectUpdate) -> Project:
        current = await self.get_or_raise(project_id)
        name = data.name if data.name is not None else current.name
        description = data.description if data.description is not None else current.description
        workspace_path = (
            data.workspace_path if data.workspace_path is not None else current.workspace_path
        )
        status = data.status if data.status is not None else current.status
        config = data.config if data.config is not None else current.config
        now = utc_now()

        await self._db.execute(
            """
            UPDATE projects
            SET name = ?, description = ?, workspace_path = ?, status = ?, config = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (name, description, workspace_path, status.value, dumps(config), now.isoformat(), project_id),
        )
        return await self.get_or_raise(project_id)

    async def delete(self, project_id: str) -> None:
        await self.get_or_raise(project_id)
        await self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
