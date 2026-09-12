"""Tests for the Prompt Optimizer half of the post-execution pipeline (see
`core.learning.post_execution.PostExecutionPipeline._process_prompt_feedback`):
a reflection's `prompt_feedback` should turn into either an activated
prompt version (only when the Learning Policy allows auto-applying the
"prompt" category) or a reviewable `prompt_proposal_generated` event
otherwise -- "prompt" is in `requires_approval_categories` by default, so
the default (ASSISTED) policy must never auto-activate one.
"""

from __future__ import annotations

from pathlib import Path

from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.database.repositories.tasks_repo import TasksRepository
from core.learning.post_execution import PostExecutionPipeline
from core.orchestrator.models import ExecutionStatus, RoutingDecision
from core.projects.models import ProjectCreate
from core.providers.mock_provider import MockProvider
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskMode, TaskStatus


def _plan_with_two_corrections(agent_id: str) -> dict:
    return {
        "strategy": "automatic", "source": "rule_based", "playbook_version_id": None,
        "intent": {"categories": ["debugging"], "risk": "low", "complexity": "medium"},
        "steps": [
            {"id": "s1", "step_type": "implementation", "required_capability": "debugging", "dependencies": []},
            {"id": "s2", "step_type": "correction", "required_capability": "debugging", "dependencies": ["s1"]},
            {"id": "s3", "step_type": "correction", "required_capability": "debugging", "dependencies": ["s2"]},
        ],
    }


async def _make_execution_needing_prompt_feedback(ctx, *, agent_id: str = "agent_claude_reviewer") -> str:
    project = await ctx.project_service.create_project(ProjectCreate(name="Prompt Feedback Test"))
    task = await ctx.task_service.create_task(TaskCreate(project_id=project.id, title="x", mode=TaskMode.AUTOMATIC))
    execution = await ctx.executions_repo.create(task_id=task.id, project_id=project.id)
    await ctx.executions_repo.update_plan(execution.id, _plan_with_two_corrections(agent_id))
    await ctx.executions_repo.update_status(execution.id, ExecutionStatus.COMPLETED, completed=True)
    await TasksRepository(ctx.db).update_status(
        task.id, TaskStatus.PARTIAL,
        result={"verification": {"passed": False, "reasons": ["still failing"], "checks": []}, "total_cost_usd": 0.05, "total_tokens": 500},
    )
    await ctx.routing_decisions_repo.record(
        execution.id, RoutingDecision(step_id="s1", agent_id=agent_id, provider="mock", model="mock-general-1", reason="x")
    )
    return execution.id


async def test_prompt_feedback_produces_a_pending_proposal_under_the_default_policy(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "prompt_feedback.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        execution_id = await _make_execution_needing_prompt_feedback(ctx)
        pipeline = PostExecutionPipeline(
            ctx.reflection_engine, ctx.reflections_repo, ctx.learning_engine, ctx.performance_tracker,
            ctx.playbook_matcher, ctx.rule_resolver, ctx.event_bus, ctx.prompt_optimizer,
        )
        await pipeline.process(execution_id)

        events = await ctx.learning_events_repo.list_recent(50)
        event_types = [e["event_type"] for e in events]
        assert "prompt_proposal_generated" in event_types
        assert "prompt_version_activated" not in event_types

        proposals = await dispatch("prompt.proposals.list", {}, ctx)
        assert len(proposals) == 1
        assert proposals[0]["evidence"]["agent_id"] == "agent_claude_reviewer"
    finally:
        await ctx.close()


async def test_a_pending_proposal_can_be_applied_by_the_user(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "apply_proposal.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        execution_id = await _make_execution_needing_prompt_feedback(ctx)
        pipeline = PostExecutionPipeline(
            ctx.reflection_engine, ctx.reflections_repo, ctx.learning_engine, ctx.performance_tracker,
            ctx.playbook_matcher, ctx.rule_resolver, ctx.event_bus, ctx.prompt_optimizer,
        )
        await pipeline.process(execution_id)
        proposals = await dispatch("prompt.proposals.list", {}, ctx)
        event_id = proposals[0]["id"]

        applied = await dispatch("prompt.proposals.apply", {"event_id": event_id}, ctx)
        assert applied["active"] is True
        assert applied["origin"] == "prompt_optimizer"

        active = await ctx.prompt_registry.get_by_key("agent_claude_reviewer")
        assert active == applied["content"]
    finally:
        await ctx.close()


async def test_autonomous_mode_can_auto_activate_a_prompt_proposal_when_configured(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "autonomous_prompt.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        await ctx.learning_policy_manager.update(
            mode="autonomous", auto_apply_categories=["prompt"], requires_approval_categories=["verification"],
        )
        execution_id = await _make_execution_needing_prompt_feedback(ctx)
        pipeline = PostExecutionPipeline(
            ctx.reflection_engine, ctx.reflections_repo, ctx.learning_engine, ctx.performance_tracker,
            ctx.playbook_matcher, ctx.rule_resolver, ctx.event_bus, ctx.prompt_optimizer,
        )
        await pipeline.process(execution_id)

        events = await ctx.learning_events_repo.list_recent(50)
        event_types = [e["event_type"] for e in events]
        assert "prompt_version_activated" in event_types
    finally:
        await ctx.close()
