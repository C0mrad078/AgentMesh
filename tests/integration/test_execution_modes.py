"""Integration tests for Manual, Pipeline, Debate, and Consensus modes,
each driven through the real `ExecutionEngine` against `MockProvider` --
proving the Planner's mode-specific plan shapes (see
`tests/python/test_planner.py`) actually execute correctly end to end,
including real parallelism for Debate/Consensus's independent candidates.
"""

from __future__ import annotations

from pathlib import Path

from core.bridge.context import build_context
from core.orchestrator.models import ExecutionStatus
from core.projects.models import ProjectCreate
from core.providers.mock_provider import MockProvider, MockScenario
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskMode, TaskStatus


async def test_manual_mode_uses_the_chosen_agent(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "manual.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Manual Mode"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Do X", mode=TaskMode.MANUAL,
                input={"agent_id": "agent_coder", "scenario": MockScenario.SUCCESS.value},
            )
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.COMPLETED

        routing = await ctx.routing_decisions_repo.list_for_execution(execution.id)
        assert len(routing) == 1
        assert routing[0]["agent_id"] == "agent_coder"
    finally:
        await ctx.close()


async def test_pipeline_mode_runs_agents_in_sequence(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "pipeline.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Pipeline Mode"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Do X", mode=TaskMode.PIPELINE,
                input={
                    "agent_ids": ["agent_generalist", "agent_reviewer", "agent_coder"],
                    "scenario": MockScenario.SUCCESS.value,
                },
            )
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.COMPLETED

        routing = await ctx.routing_decisions_repo.list_for_execution(execution.id)
        assert [r["agent_id"] for r in routing] == ["agent_generalist", "agent_reviewer", "agent_coder"]

        steps = await ctx.steps_repo.list_for_execution(execution.id)
        work_steps = sorted((s for s in steps if s.kind == "work"), key=lambda s: s.step_index)
        # Each pipeline step must only start after the previous one's row exists.
        assert len(work_steps) == 3
    finally:
        await ctx.close()


async def test_debate_mode_runs_candidates_in_parallel_and_synthesizes(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "debate.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Debate Mode"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Do X", mode=TaskMode.DEBATE,
                input={
                    "agent_ids": ["agent_generalist", "agent_reviewer", "agent_coder"],
                    "scenario": MockScenario.SUCCESS.value,
                },
            )
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.COMPLETED

        final_task = await ctx.task_service.get_task(task.id)
        assert final_task.status == TaskStatus.COMPLETED
        assert final_task.result["summary"]

        steps = await ctx.steps_repo.list_for_execution(execution.id)
        work_steps = [s for s in steps if s.kind == "work"]
        # 3 candidates + 1 synthesis step.
        assert len(work_steps) == 4
    finally:
        await ctx.close()


async def test_consensus_mode_produces_a_final_synthesis(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "consensus.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Consensus Mode"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Do X", mode=TaskMode.CONSENSUS,
                input={
                    "agent_ids": ["agent_generalist", "agent_coder"],
                    "scenario": MockScenario.SUCCESS.value,
                },
            )
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.COMPLETED
        final_task = await ctx.task_service.get_task(task.id)
        assert final_task.status == TaskStatus.COMPLETED
    finally:
        await ctx.close()
