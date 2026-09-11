"""End-to-end tests for the full local execution engine, exercised the way
the bridge itself would: create a project, create a task, run it through
Intent Analyzer -> Planner -> Router -> Executor -> Verifier -> Aggregator
against `MockProvider`, and confirm the result is durably persisted and
survives reopening the database (a fresh `BridgeContext` against the same
file, standing in for "close/reopen the app").
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.bridge.context import build_context
from core.orchestrator.models import ExecutionStatus, StepStatus
from core.projects.models import ProjectCreate
from core.providers.mock_provider import MockScenario
from core.tasks.models import TaskCreate, TaskStatus


async def test_full_pipeline_success(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "flow.db")
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Flow Project"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id,
                title="Write a summary",
                input={"scenario": MockScenario.SUCCESS.value},
            )
        )

        execution = await ctx.engine.run(task)

        assert execution.status == ExecutionStatus.COMPLETED

        final_task = await ctx.task_service.get_task(task.id)
        assert final_task.status == TaskStatus.COMPLETED
        assert final_task.result is not None

        steps = await ctx.steps_repo.list_for_execution(execution.id)
        phase_steps = [s for s in steps if s.kind == "phase"]
        assert len(phase_steps) == 6
        assert all(s.status == StepStatus.COMPLETED for s in phase_steps)
    finally:
        await ctx.db.close()


async def test_full_pipeline_persists_and_survives_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "persist.db"
    ctx1 = await build_context(db_path)
    try:
        project = await ctx1.project_service.create_project(ProjectCreate(name="Reopen Project"))
        task = await ctx1.task_service.create_task(
            TaskCreate(project_id=project.id, title="Persisted task")
        )
        execution = await ctx1.engine.run(task)
        execution_id = execution.id
        task_id = task.id
    finally:
        await ctx1.db.close()

    ctx2 = await build_context(db_path)
    try:
        reloaded_task = await ctx2.task_service.get_task(task_id)
        assert reloaded_task.status == TaskStatus.COMPLETED

        reloaded_execution = await ctx2.executions_repo.get_or_raise(execution_id)
        assert reloaded_execution.status == ExecutionStatus.COMPLETED

        steps = await ctx2.steps_repo.list_for_execution(execution_id)
        assert len(steps) >= 6
    finally:
        await ctx2.db.close()


async def test_full_pipeline_retry_scenario_recovers(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "retry.db")
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Retry Project"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id,
                title="Retry then succeed",
                input={"scenario": MockScenario.RETRY_THEN_SUCCESS.value, "fail_count": 1},
            )
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.COMPLETED

        steps = await ctx.steps_repo.list_for_execution(execution.id)
        work_steps = [s for s in steps if s.kind == "work"]
        assert len(work_steps) == 1
        assert work_steps[0].attempt == 2
    finally:
        await ctx.db.close()


async def test_full_pipeline_persistent_failure_marks_task_failed(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "fail.db")
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Fail Project"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id,
                title="Always fails",
                input={"scenario": MockScenario.PERSISTENT_ERROR.value},
            )
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.FAILED

        final_task = await ctx.task_service.get_task(task.id)
        assert final_task.status == TaskStatus.FAILED
    finally:
        await ctx.db.close()


async def test_full_pipeline_cancellation_stops_the_run(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "cancel.db")
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Cancel Project"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id,
                title="Cancel this",
                input={"scenario": MockScenario.LATENCY.value, "latency_seconds": 2.0},
            )
        )

        run_task = asyncio.create_task(ctx.engine.run(task))
        await asyncio.sleep(0.1)

        # Find the execution the engine just created so we can cancel it.
        executions = await ctx.executions_repo.list_for_project(project.id)
        assert len(executions) == 1
        cancelled = ctx.engine.request_cancel(executions[0].id)
        assert cancelled is True

        loop = asyncio.get_event_loop()
        start = loop.time()
        execution = await run_task
        elapsed = loop.time() - start

        assert execution.status == ExecutionStatus.CANCELLED
        assert elapsed < 1.5  # would be ~2s+ if cancellation weren't real

        final_task = await ctx.task_service.get_task(task.id)
        assert final_task.status == TaskStatus.CANCELLED
    finally:
        await ctx.db.close()
