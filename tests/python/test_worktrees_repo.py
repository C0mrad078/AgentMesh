from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.worktrees_repo import WorktreesRepository
from core.projects.models import ProjectCreate
from core.worktrees.models import WorktreeCreate, WorktreeStatus


async def _project(tmp_db: Database) -> str:
    project = await ProjectsRepository(tmp_db).create(ProjectCreate(name="AgentMash"))
    return project.id


async def test_create_worktree_defaults_to_active(tmp_db: Database) -> None:
    project_id = await _project(tmp_db)
    repo = WorktreesRepository(tmp_db)
    worktree = await repo.create(
        WorktreeCreate(
            project_id=project_id, branch_name="agentmash/task-123-atlas",
            path="/tmp/agentmash/.agentmash/worktrees/session-a",
        )
    )
    assert worktree.status == WorktreeStatus.ACTIVE
    assert worktree.removed_at is None


async def test_list_by_project_only_active_by_default(tmp_db: Database) -> None:
    project_id = await _project(tmp_db)
    repo = WorktreesRepository(tmp_db)
    active = await repo.create(
        WorktreeCreate(project_id=project_id, branch_name="b1", path="/tmp/wt1")
    )
    cleaned = await repo.create(
        WorktreeCreate(project_id=project_id, branch_name="b2", path="/tmp/wt2")
    )
    await repo.mark_status(cleaned.id, WorktreeStatus.CLEANED)

    only_active = await repo.list_by_project(project_id)
    everything = await repo.list_by_project(project_id, only_active=False)
    assert [w.id for w in only_active] == [active.id]
    assert {w.id for w in everything} == {active.id, cleaned.id}


async def test_mark_status_cleaned_sets_removed_at(tmp_db: Database) -> None:
    project_id = await _project(tmp_db)
    repo = WorktreesRepository(tmp_db)
    worktree = await repo.create(WorktreeCreate(project_id=project_id, branch_name="b1", path="/tmp/wt1"))

    cleaned = await repo.mark_status(worktree.id, WorktreeStatus.CLEANED)
    assert cleaned.removed_at is not None

    conflict = await repo.mark_status(worktree.id, WorktreeStatus.CONFLICT)
    assert conflict.removed_at is None
