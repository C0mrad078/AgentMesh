from __future__ import annotations

import asyncio
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from core.database.repositories.missions_repo import MissionsRepository
from core.database.repositories.parallel_repo import ParallelRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.missions.models import Mission, PlannedTask
from core.parallel.concurrency import ParallelConcurrency, ParallelLimits
from core.parallel.forecast import forecast
from core.parallel.models import ConcurrencyLease, ForecastLevel
from core.parallel.worktrees import WorktreeManager
from core.projects.models import ProjectCreate
from core.tasks.models import TaskCreate
from core.utils.errors import ValidationError
from core.utils.ids import new_id
from core.utils.time import utc_now


def _git(path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, check=True, text=True,
                            capture_output=True)
    return result.stdout.strip()


async def test_forecast_marks_overlapping_and_adjacent_paths():
    values = forecast("m1", [
        PlannedTask(key="backend", title="Backend", description="update backend", capabilities=["coding"], acceptance=["works"], expected_paths=["core/api.py"]),
        PlannedTask(key="frontend", title="Frontend", description="update frontend", capabilities=["coding"], acceptance=["works"], expected_paths=["desktop/src/App.tsx"]),
        PlannedTask(key="tests", title="Tests", description="update tests", capabilities=["coding"], acceptance=["works"], expected_paths=["core/api.py", "tests/test_api.py"]),
    ])
    levels = {(v.task_id, v.other_task_id): v.level for v in values}
    assert levels[("backend", "tests")] == ForecastLevel.CONFIRMED
    assert levels[("frontend", "tests")] == ForecastLevel.POSSIBLE


async def test_persistent_concurrency_limits_and_expiration(tmp_db):
    repo = ParallelRepository(tmp_db)
    now = utc_now()
    limits = {"global": 1, "provider": 1, "project": 1, "mission": 1}
    first = ConcurrencyLease(id=new_id("lease"), mission_id="m", task_id="a", project_id="p",
                             provider="codex", expires_at=now + timedelta(minutes=5), created_at=now)
    second = first.model_copy(update={"id": new_id("lease"), "task_id": "b"})
    project = await ProjectsRepository(tmp_db).create(ProjectCreate(name="lease-project"))
    mission = Mission(id="m", project_id=project.id, request="lease", created_at=now, updated_at=now)
    await MissionsRepository(tmp_db).put(mission, command_id="lease-command")
    tasks = TasksRepository(tmp_db)
    task_a = await tasks.create(TaskCreate(project_id=project.id, title="Lease A"))
    task_b = await tasks.create(TaskCreate(project_id=project.id, title="Lease B"))
    first = first.model_copy(update={"project_id": project.id})
    first = first.model_copy(update={"task_id": task_a.id})
    second = second.model_copy(update={"project_id": project.id, "task_id": task_b.id})
    assert await repo.acquire(first, limits=limits)
    assert not await repo.acquire(second, limits=limits)
    await repo.release(mission_id="m", task_id=task_a.id)
    assert await repo.acquire(second, limits=limits)


async def test_worktree_manager_isolates_branches_and_preserves_main(tmp_db, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _git(project_root, "init", "-q", "-b", "main")
    _git(project_root, "config", "user.email", "test@example.invalid")
    _git(project_root, "config", "user.name", "AgentMash Test")
    (project_root / "README.md").write_text("base\n")
    _git(project_root, "add", "README.md")
    _git(project_root, "commit", "-qm", "base")
    base = _git(project_root, "rev-parse", "HEAD")
    project = await ProjectsRepository(tmp_db).create(ProjectCreate(name="fixture", workspace_path=str(project_root)))
    mission = Mission(id="mission-wt", project_id=project.id, request="parallel", created_at=utc_now(), updated_at=utc_now())
    await MissionsRepository(tmp_db).put(mission, command_id="wt-command")
    tasks = TasksRepository(tmp_db)
    task_a = await tasks.create(TaskCreate(project_id=project.id, title="A"))
    task_b = await tasks.create(TaskCreate(project_id=project.id, title="B"))
    manager = WorktreeManager(ParallelRepository(tmp_db))
    first, second = await asyncio.gather(
        manager.create(mission=mission, task_id=task_a.id, project_root=project_root,
                       base_sha=base, branch_name="agentmash/mission-mission-wt/task-task-a"),
        manager.create(mission=mission, task_id=task_b.id, project_root=project_root,
                       base_sha=base, branch_name="agentmash/mission-mission-wt/task-task-b"),
    )
    assert first.path != second.path
    assert first.base_sha == second.base_sha == base
    assert _git(project_root, "branch", "--show-current") == "main"
    first_path = Path(first.path) / "backend.py"
    first_path.write_text("one\n")
    sha = await manager.commit(first, "task a")
    assert sha != base
    assert _git(project_root, "rev-parse", "HEAD") == base
    assert not (Path(second.path) / "backend.py").exists()


def test_concurrency_configuration_rejects_zero():
    limits = ParallelConcurrency(ParallelLimits(global_sessions=0))
    with pytest.raises(ValidationError):
        limits.validate()
