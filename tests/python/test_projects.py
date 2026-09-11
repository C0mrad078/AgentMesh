from __future__ import annotations

import pydantic
import pytest
from core.database.connection import Database
from core.database.repositories.projects_repo import ProjectsRepository
from core.projects.models import ProjectCreate, ProjectStatus, ProjectUpdate
from core.projects.service import ProjectService
from core.utils.errors import NotFoundError, ValidationError


def _service(db: Database) -> ProjectService:
    return ProjectService(ProjectsRepository(db))


async def test_create_project(tmp_db: Database) -> None:
    service = _service(tmp_db)
    project = await service.create_project(ProjectCreate(name="My Project", description="desc"))
    assert project.id
    assert project.name == "My Project"
    assert project.status == ProjectStatus.ACTIVE


async def test_create_project_rejects_blank_name(tmp_db: Database) -> None:
    with pytest.raises(pydantic.ValidationError):
        ProjectCreate(name="   ")


async def test_get_project(tmp_db: Database) -> None:
    service = _service(tmp_db)
    created = await service.create_project(ProjectCreate(name="Findable"))
    fetched = await service.get_project(created.id)
    assert fetched.id == created.id
    assert fetched.name == "Findable"


async def test_get_missing_project_raises(tmp_db: Database) -> None:
    service = _service(tmp_db)
    with pytest.raises(NotFoundError):
        await service.get_project("does-not-exist")


async def test_list_projects(tmp_db: Database) -> None:
    service = _service(tmp_db)
    await service.create_project(ProjectCreate(name="A"))
    await service.create_project(ProjectCreate(name="B"))
    projects = await service.list_projects()
    assert len(projects) == 2


async def test_update_project(tmp_db: Database) -> None:
    service = _service(tmp_db)
    created = await service.create_project(ProjectCreate(name="Old Name"))
    updated = await service.update_project(created.id, ProjectUpdate(name="New Name"))
    assert updated.name == "New Name"
    assert updated.id == created.id


async def test_archived_projects_excluded_by_default(tmp_db: Database) -> None:
    service = _service(tmp_db)
    created = await service.create_project(ProjectCreate(name="Archivable"))
    await service.update_project(created.id, ProjectUpdate(status=ProjectStatus.ARCHIVED))
    active = await service.list_projects()
    everything = await service.list_projects(include_archived=True)
    assert created.id not in [p.id for p in active]
    assert created.id in [p.id for p in everything]


async def test_workspace_path_traversal_rejected(tmp_db: Database) -> None:
    service = _service(tmp_db)
    with pytest.raises(ValidationError):
        await service.create_project(ProjectCreate(name="Bad", workspace_path="../../etc"))


async def test_reopen_project_after_recreating_service(tmp_db: Database) -> None:
    service = _service(tmp_db)
    created = await service.create_project(ProjectCreate(name="Persisted"))

    other_service = ProjectService(ProjectsRepository(tmp_db))
    fetched = await other_service.get_project(created.id)
    assert fetched.name == "Persisted"
