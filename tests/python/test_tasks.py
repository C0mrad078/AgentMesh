from __future__ import annotations

import pytest
from core.agents.models import Agent
from core.database.connection import Database
from core.database.repositories.agents_repo import AgentsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.providers_repo import ProvidersRepository
from core.database.repositories.sessions_repo import SessionsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.database.repositories.teams_repo import TeamsRepository
from core.projects.models import ProjectCreate
from core.projects.service import ProjectService
from core.runtime.execution_backend import ExecutionBackendType
from core.sessions.models import SessionCreate
from core.tasks.models import TaskCreate, TaskStatus
from core.tasks.service import TaskService
from core.tasks.state_machine import can_transition
from core.teams.models import TeamCreate
from core.utils.errors import InvalidStateTransitionError, ValidationError


async def _make_project(db: Database) -> str:
    service = ProjectService(ProjectsRepository(db))
    project = await service.create_project(ProjectCreate(name="Task Project"))
    return project.id


async def test_task_created_as_queued(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    service = TaskService(TasksRepository(tmp_db))
    task = await service.create_task(TaskCreate(project_id=project_id, title="Do a thing"))
    assert task.status == TaskStatus.QUEUED


async def test_queued_to_running_to_completed(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    service = TaskService(TasksRepository(tmp_db))
    task = await service.create_task(TaskCreate(project_id=project_id, title="Flow"))

    running = await service.transition(task.id, TaskStatus.RUNNING)
    assert running.status == TaskStatus.RUNNING
    assert running.started_at is not None

    completed = await service.transition(task.id, TaskStatus.COMPLETED, result={"ok": True})
    assert completed.status == TaskStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.result == {"ok": True}


async def test_running_to_failed(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    service = TaskService(TasksRepository(tmp_db))
    task = await service.create_task(TaskCreate(project_id=project_id, title="Will fail"))
    await service.transition(task.id, TaskStatus.RUNNING)
    failed = await service.transition(task.id, TaskStatus.FAILED, result={"error": "boom"})
    assert failed.status == TaskStatus.FAILED


async def test_cancel_task(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    service = TaskService(TasksRepository(tmp_db))
    task = await service.create_task(TaskCreate(project_id=project_id, title="Cancel me"))
    cancelled = await service.cancel_task(task.id)
    assert cancelled.status == TaskStatus.CANCELLED


async def test_cancel_task_rejects_a_task_that_is_already_running(tmp_db: Database) -> None:
    """`task.cancel` only covers work that has not started yet -- once an
    ExecutionEngine is actually running the task, only `execution.cancel`
    can interrupt it for real. Force-flipping the task row here would just
    make the status lie about what is actually happening.
    """
    project_id = await _make_project(tmp_db)
    service = TaskService(TasksRepository(tmp_db))
    task = await service.create_task(TaskCreate(project_id=project_id, title="Already running"))
    await service.transition(task.id, TaskStatus.RUNNING)

    with pytest.raises(ValidationError):
        await service.cancel_task(task.id)

    reloaded = await service.get_task(task.id)
    assert reloaded.status == TaskStatus.RUNNING


async def test_completed_task_cannot_go_back_to_running(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    service = TaskService(TasksRepository(tmp_db))
    task = await service.create_task(TaskCreate(project_id=project_id, title="Terminal"))
    await service.transition(task.id, TaskStatus.RUNNING)
    await service.transition(task.id, TaskStatus.COMPLETED)

    with pytest.raises(InvalidStateTransitionError):
        await service.transition(task.id, TaskStatus.RUNNING)


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        (TaskStatus.QUEUED, TaskStatus.RUNNING, True),
        (TaskStatus.QUEUED, TaskStatus.COMPLETED, False),
        (TaskStatus.RUNNING, TaskStatus.WAITING, True),
        (TaskStatus.RUNNING, TaskStatus.REVIEWING, True),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING, False),
        (TaskStatus.FAILED, TaskStatus.RUNNING, False),
        (TaskStatus.CANCELLED, TaskStatus.RUNNING, False),
        (TaskStatus.REVIEWING, TaskStatus.RUNNING, True),
        (TaskStatus.REVIEWING, TaskStatus.COMPLETED, True),
    ],
)
def test_state_machine_transitions(current: TaskStatus, target: TaskStatus, expected: bool) -> None:
    assert can_transition(current, target) is expected


async def test_recover_stale_running_tasks_on_startup(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    service = TaskService(TasksRepository(tmp_db))
    task = await service.create_task(TaskCreate(project_id=project_id, title="Interrupted"))
    await service.transition(task.id, TaskStatus.RUNNING)

    recovered = await service.recover_stale_tasks()
    assert len(recovered) == 1
    assert recovered[0].status == TaskStatus.FAILED

    reloaded = await service.get_task(task.id)
    assert reloaded.status == TaskStatus.FAILED
    assert reloaded.result is not None
    assert reloaded.result["recovered"] is True


# -- Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): explicit
# agent/team/session assignment, all nullable and independent of the
# DAG-level PlanStep/Router assignment system above. -----------------------


async def test_task_can_be_created_with_an_explicit_agent_and_team_assignment(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    await AgentsRepository(tmp_db).upsert(Agent(id="agent_atlas", name="Atlas", provider="claude_code_cli"))
    team = await TeamsRepository(tmp_db).create(TeamCreate(name="Core"))

    repo = TasksRepository(tmp_db)
    task = await repo.create(
        TaskCreate(
            project_id=project_id, title="Refactor auth", assigned_agent_id="agent_atlas",
            assigned_team_id=team.id,
        )
    )
    assert task.assigned_agent_id == "agent_atlas"
    assert task.assigned_team_id == team.id
    assert task.session_id is None


async def test_task_without_explicit_assignment_leaves_fields_unset(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    repo = TasksRepository(tmp_db)
    task = await repo.create(TaskCreate(project_id=project_id, title="Automatic"))
    assert task.assigned_agent_id is None
    assert task.assigned_team_id is None
    assert task.session_id is None


async def test_assign_session_links_a_task_to_a_real_session(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    await AgentsRepository(tmp_db).upsert(Agent(id="agent_atlas", name="Atlas", provider="claude_code_cli"))
    claude = await ProvidersRepository(tmp_db).get_by_name("claude")
    assert claude is not None

    session = await SessionsRepository(tmp_db).create(
        SessionCreate(
            agent_id="agent_atlas", project_id=project_id, provider_id=claude.id,
            backend_type=ExecutionBackendType.SUBSCRIPTION,
        )
    )
    repo = TasksRepository(tmp_db)
    task = await repo.create(TaskCreate(project_id=project_id, title="Real session work"))

    updated = await repo.assign_session(task.id, session.id)
    assert updated.session_id == session.id
