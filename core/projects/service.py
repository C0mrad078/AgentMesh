"""Project service: business rules layered on top of the projects repository."""

from __future__ import annotations

from pathlib import Path

from core.database.repositories.projects_repo import ProjectsRepository
from core.projects.models import Project, ProjectCreate, ProjectUpdate
from core.security.audit import AuditLogger
from core.utils.errors import ValidationError


class ProjectService:
    def __init__(self, repository: ProjectsRepository, audit: AuditLogger | None = None) -> None:
        self._repository = repository
        self._audit = audit

    async def create_project(self, data: ProjectCreate) -> Project:
        if data.workspace_path:
            self._validate_workspace_path(data.workspace_path)
        project = await self._repository.create(data)
        if self._audit:
            await self._audit.log("project.create", "project", project.id, {"name": project.name})
        return project

    async def get_project(self, project_id: str) -> Project:
        return await self._repository.get_or_raise(project_id)

    async def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        return await self._repository.list(include_archived=include_archived)

    async def update_project(self, project_id: str, data: ProjectUpdate) -> Project:
        if data.workspace_path:
            self._validate_workspace_path(data.workspace_path)
        project = await self._repository.update(project_id, data)
        if self._audit:
            await self._audit.log("project.update", "project", project.id, {})
        return project

    async def delete_project(self, project_id: str) -> None:
        await self._repository.delete(project_id)
        if self._audit:
            await self._audit.log("project.delete", "project", project_id, {})

    @staticmethod
    def _validate_workspace_path(workspace_path: str) -> None:
        """Reject relative paths and traversal segments up front.

        This is a first line of defense; the authoritative check happens in
        `core.tools.path_guard` whenever a tool actually touches the
        filesystem, since a workspace path is only a *hint* until then.
        """
        if ".." in Path(workspace_path).parts:
            raise ValidationError("Workspace path cannot contain '..' segments.")
