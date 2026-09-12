"""Startup crash recovery -- previously had zero test coverage. Simulates
the "app was killed mid-task" scenario the Stage 4 brief calls out:
`execution running -> core killed -> restart -> recovery`, using the real
repositories/services against a fresh database rather than a live process
kill (which isn't reproducible in a unit test)."""

from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.executions_repo import ExecutionsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.orchestrator.models import ExecutionStatus
from core.orchestrator.recovery import RecoveryState, recover_interrupted_work
from core.projects.models import ProjectCreate
from core.tasks.models import TaskCreate, TaskStatus
from core.tasks.service import TaskService


async def _make_running_task_and_execution(db: Database) -> tuple[str, str]:
    project = await ProjectsRepository(db).create(ProjectCreate(name="Recovery Test"))
    task = await TasksRepository(db).create(TaskCreate(project_id=project.id, title="x"))
    await TasksRepository(db).update_status(task.id, TaskStatus.RUNNING)
    execution = await ExecutionsRepository(db).create(task_id=task.id, project_id=project.id)
    return task.id, execution.id


async def test_a_running_task_left_by_a_crash_is_marked_failed_on_restart(tmp_db: Database) -> None:
    task_id, _ = await _make_running_task_and_execution(tmp_db)

    task_service = TaskService(TasksRepository(tmp_db))
    report = await recover_interrupted_work(task_service, ExecutionsRepository(tmp_db))

    assert task_id in report.recovered_task_ids
    task = await TasksRepository(tmp_db).get_or_raise(task_id)
    assert task.status == TaskStatus.FAILED
    assert task.result["recovered"] is True


async def test_a_running_execution_left_by_a_crash_is_marked_failed_with_a_recovery_reason(tmp_db: Database) -> None:
    _, execution_id = await _make_running_task_and_execution(tmp_db)

    task_service = TaskService(TasksRepository(tmp_db))
    report = await recover_interrupted_work(task_service, ExecutionsRepository(tmp_db))

    assert execution_id in report.recovered_execution_ids
    execution = await ExecutionsRepository(tmp_db).get_or_raise(execution_id)
    assert execution.status == ExecutionStatus.FAILED
    assert execution.error["recovery_state"] == RecoveryState.FAILED_INTERRUPTED.value


async def test_recovery_never_leaves_a_task_running(tmp_db: Database) -> None:
    await _make_running_task_and_execution(tmp_db)
    task_service = TaskService(TasksRepository(tmp_db))
    await recover_interrupted_work(task_service, ExecutionsRepository(tmp_db))

    remaining_running = await TasksRepository(tmp_db).find_stale_running()
    assert remaining_running == []


async def test_recovery_is_a_no_op_when_nothing_was_interrupted(tmp_db: Database) -> None:
    task_service = TaskService(TasksRepository(tmp_db))
    report = await recover_interrupted_work(task_service, ExecutionsRepository(tmp_db))
    assert report.recovered_task_ids == []
    assert report.recovered_execution_ids == []


async def test_a_completed_task_and_execution_are_left_untouched(tmp_db: Database) -> None:
    project = await ProjectsRepository(tmp_db).create(ProjectCreate(name="Completed"))
    task = await TasksRepository(tmp_db).create(TaskCreate(project_id=project.id, title="x"))
    await TasksRepository(tmp_db).update_status(task.id, TaskStatus.COMPLETED, result={"ok": True})
    execution = await ExecutionsRepository(tmp_db).create(task_id=task.id, project_id=project.id)
    await ExecutionsRepository(tmp_db).update_status(execution.id, ExecutionStatus.COMPLETED, completed=True)

    task_service = TaskService(TasksRepository(tmp_db))
    report = await recover_interrupted_work(task_service, ExecutionsRepository(tmp_db))

    assert task.id not in report.recovered_task_ids
    assert execution.id not in report.recovered_execution_ids
    refreshed_task = await TasksRepository(tmp_db).get_or_raise(task.id)
    assert refreshed_task.status == TaskStatus.COMPLETED
