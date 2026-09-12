"""End-to-end integration tests for the Stage 3 post-execution pipeline,
driven through the real `ExecutionEngine` + `build_context` wiring against
`MockProvider` -- proving Reflection Engine -> Learning Engine actually
runs after a real execution, not just in isolation against hand-built
fixtures (see `tests/python/test_reflection_engine.py` /
`test_learning_engine.py` for the unit-level coverage).
"""

from __future__ import annotations

from pathlib import Path

from core.bridge.context import build_context
from core.database.connection import Database
from core.database.repositories.reflections_repo import ReflectionsRepository
from core.orchestrator.models import ExecutionStatus
from core.projects.models import ProjectCreate
from core.providers.mock_provider import MockProvider
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskMode


async def test_a_completed_execution_produces_a_persisted_reflection(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "reflect.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Reflect"))
        task = await ctx.task_service.create_task(
            TaskCreate(project_id=project.id, title="Corrija o erro de autenticação", mode=TaskMode.AUTOMATIC)
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.COMPLETED

        await ctx.engine.wait_for_pending_reflections()

        reflections = await ctx.reflections_repo.list_for_execution(execution.id)
        assert len(reflections) == 1
        assert reflections[0]["overall_score"] > 0

        events = await ctx.execution_events_repo.list_for_execution(execution.id)
        event_types = {e["event_type"] for e in events}
        assert "reflection.started" in event_types
        assert "reflection.completed" in event_types
    finally:
        await ctx.close()


async def test_model_performance_is_updated_after_a_real_execution(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "perf.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Perf"))
        task = await ctx.task_service.create_task(
            TaskCreate(project_id=project.id, title="Refatore o módulo de pagamentos", mode=TaskMode.AUTOMATIC)
        )
        await ctx.engine.run(task)
        await ctx.engine.wait_for_pending_reflections()

        summaries = await ctx.performance_tracker.list_all_summaries()
        assert len(summaries) > 0
        assert all(s["executions"] >= 1 for s in summaries)
    finally:
        await ctx.close()


async def test_repeated_similar_executions_build_a_candidate_toward_promotion(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "learn.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        await ctx.learning_policy_manager.update(
            mode="assisted", minimum_observations_for_activation=2, minimum_confidence=0.05,
            auto_apply_categories=["planning", "agent_selection", "efficiency", "tool_use", "cost", "context", "strategy"],
        )
        project = await ctx.project_service.create_project(ProjectCreate(name="Repeated"))

        for _ in range(3):
            task = await ctx.task_service.create_task(
                TaskCreate(
                    project_id=project.id,
                    title="Analise a autenticação e corrija vulnerabilidades de segurança",
                    mode=TaskMode.AUTOMATIC,
                )
            )
            await ctx.engine.run(task)
            await ctx.engine.wait_for_pending_reflections()

        candidates = await ctx.learning_candidates_repo.list_all()
        assert len(candidates) > 0
        # At least one candidate accumulated more than one observation --
        # the same underlying insight was recognized across executions
        # rather than creating a fresh candidate every time.
        assert any(c["observations"] > 1 for c in candidates)
    finally:
        await ctx.close()


async def test_a_rule_that_starts_producing_worse_outcomes_can_be_rolled_back_without_breaking_execution(
    tmp_path: Path,
) -> None:
    ctx = await build_context(tmp_path / "rollback.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        rule = await ctx.learned_rules_repo.create(
            title="Regra ruim", category="agent_selection", rule_text="x", scope_type="global",
            scope_value=None, priority="normal", confidence=0.6, observations=1, successes=1,
            failures=0, distinct_projects=["p1"], status="active", origin="learning_engine",
        )
        await ctx.learned_rules_repo.update_action(rule["id"], {"effect": "avoid_agent", "agent_id": "agent_coder"})

        for _ in range(6):
            await ctx.learning_engine.record_rule_outcome(rule["id"], execution_id=None, project_id="p1", success=False)

        refreshed = await ctx.learned_rules_repo.get(rule["id"])
        assert refreshed["status"] == "deprecated"

        # The system keeps working normally after the rollback -- a real
        # execution still completes.
        project = await ctx.project_service.create_project(ProjectCreate(name="After Rollback"))
        task = await ctx.task_service.create_task(
            TaskCreate(project_id=project.id, title="Corrija um bug simples", mode=TaskMode.AUTOMATIC)
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.COMPLETED
    finally:
        await ctx.close()


async def test_closing_the_context_waits_for_a_pending_reflection_to_finish(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "close.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    project = await ctx.project_service.create_project(ProjectCreate(name="Close Race"))
    task = await ctx.task_service.create_task(
        TaskCreate(project_id=project.id, title="Corrija um bug simples", mode=TaskMode.AUTOMATIC)
    )
    execution = await ctx.engine.run(task)
    # `run()` already schedules the reflection in the background; closing
    # right after it returns must not race the reflection against a
    # closed DB/provider pool.
    await ctx.close()

    reopened = Database(tmp_path / "close.db")
    await reopened.connect()
    try:
        reflections = await ReflectionsRepository(reopened).list_for_execution(execution.id)
        assert len(reflections) == 1
    finally:
        await reopened.close()
