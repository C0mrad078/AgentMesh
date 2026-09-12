from __future__ import annotations

from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.learning.models import ImprovementCandidate, RuleCategory, RuleScope
from core.memory.models import MemoryWrite
from core.projects.models import ProjectCreate
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate
from core.utils.errors import ValidationError


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "bridge-learning.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.close()


async def test_playbooks_are_seeded_and_listable(ctx) -> None:
    playbooks = await dispatch("playbook.list", {}, ctx)
    assert len(playbooks) == 2
    versions = await dispatch("playbook.versions.list", {"playbook_id": playbooks[0]["id"]}, ctx)
    assert len(versions) == 1


async def test_learning_policy_get_and_set_roundtrip(ctx) -> None:
    policy = await dispatch("learning.policy.get", {}, ctx)
    assert policy["mode"] == "assisted"

    updated = await dispatch("learning.policy.set", {"mode": "autonomous", "max_changes_per_day": 2}, ctx)
    assert updated["mode"] == "autonomous"
    assert updated["max_changes_per_day"] == 2


async def test_user_can_create_pin_and_rollback_a_rule(ctx) -> None:
    rule = await dispatch("learning.rules.create", {
        "title": "Regra manual", "category": "routing", "rule_text": "Preferir X para Y.",
    }, ctx)
    assert rule["status"] == "active"
    assert rule["source"] == "user"

    pinned = await dispatch("learning.rules.pin", {"rule_id": rule["id"]}, ctx)
    assert pinned["pinned"] is True

    unpinned = await dispatch("learning.rules.unpin", {"rule_id": rule["id"]}, ctx)
    assert unpinned["pinned"] is False

    rolled_back = await dispatch("learning.rules.rollback", {"rule_id": rule["id"], "reason": "não funcionou"}, ctx)
    assert rolled_back["status"] == "deprecated"

    events = await dispatch("learning.events.list", {}, ctx)
    event_types = [e["event_type"] for e in events]
    assert "user_rule_created" in event_types
    assert "rule_rolled_back" in event_types


async def test_candidate_approve_and_reject_flow(ctx) -> None:
    candidate = ImprovementCandidate(
        category=RuleCategory.AGENT_SELECTION, title="Candidato de teste",
        rule_text="Não utilizar X quando Y.", scope=RuleScope.GLOBAL,
    )
    outcome = await ctx.learning_engine.process_candidate(candidate, project_id="p1", reflection_id=None)

    candidates = await dispatch("learning.candidates.list", {}, ctx)
    assert any(c["id"] == outcome.candidate_id for c in candidates)

    approved_rule = await dispatch("learning.candidates.approve", {"candidate_id": outcome.candidate_id}, ctx)
    assert approved_rule["status"] == "active"


async def test_candidate_rejection_persists_the_reason(ctx) -> None:
    candidate = ImprovementCandidate(
        category=RuleCategory.COST, title="Outro candidato", rule_text="Usar apenas um modelo.",
        scope=RuleScope.GLOBAL,
    )
    outcome = await ctx.learning_engine.process_candidate(candidate, project_id="p1", reflection_id=None)
    rejected = await dispatch(
        "learning.candidates.reject", {"candidate_id": outcome.candidate_id, "reason": "não é útil"}, ctx
    )
    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "não é útil"


async def test_model_performance_list_is_empty_before_any_execution(ctx) -> None:
    assert await dispatch("model_performance.list", {}, ctx) == []


async def test_prompt_versions_list_and_rollback(ctx) -> None:
    versions = await dispatch("prompt.versions.list", {"owner_key": "planner"}, ctx)
    assert len(versions) == 1
    v1_id = versions[0]["id"]

    await ctx.prompt_registry.create_version_by_key(
        "planner", name="v2", content="new content", prompt_type="planner",
        author="user", origin="user", reason="manual edit",
    )
    rolled_back = await dispatch(
        "prompt.rollback", {"owner_key": "planner", "target_version_id": v1_id, "reason": "regressed"}, ctx
    )
    assert rolled_back["origin"] == "rollback"

    active = await dispatch("prompt.versions.list", {"owner_key": "planner"}, ctx)
    assert next(v for v in active if v["active"])["id"] == rolled_back["id"]


async def test_learning_export_includes_every_domain(ctx) -> None:
    export = await dispatch("learning.export", {}, ctx)
    assert set(export.keys()) == {"rules", "candidates", "playbooks", "policy"}
    assert len(export["playbooks"]) == 2


async def test_learning_reset_requires_explicit_confirmation(ctx) -> None:
    with pytest.raises(ValidationError):
        await dispatch("learning.reset", {"scope": "playbooks"}, ctx)


async def test_learning_reset_archives_rules_when_scope_is_learned_rules(ctx) -> None:
    rule = await dispatch("learning.rules.create", {
        "title": "Regra a resetar", "category": "routing", "rule_text": "x",
    }, ctx)
    result = await dispatch("learning.reset", {"scope": "learned_rules", "confirm": True}, ctx)
    assert result["reset"] == ["learned_rules"]

    rules = await dispatch("learning.rules.list", {}, ctx)
    updated = next(r for r in rules if r["id"] == rule["id"])
    assert updated["status"] == "archived"


async def test_memory_list_and_history_via_bridge(ctx) -> None:
    project = await ctx.project_service.create_project(ProjectCreate(name="Memory Bridge Test"))
    await ctx.memory_store.remember(MemoryWrite(project_id=project.id, key="stack", value={"language": "Python"}))
    await ctx.memory_store.remember(MemoryWrite(project_id=project.id, key="stack", value={"language": "TypeScript"}))

    active = await dispatch("memory.list", {"project_id": project.id}, ctx)
    assert len(active) == 1
    assert active[0]["value"] == {"language": "TypeScript"}

    history = await dispatch("memory.history", {"project_id": project.id, "key": "stack"}, ctx)
    assert len(history) == 2


async def test_context_optimizer_suggestions_via_bridge(ctx) -> None:
    project = await ctx.project_service.create_project(ProjectCreate(name="Context Optimizer Test"))
    task = await ctx.task_service.create_task(TaskCreate(project_id=project.id, title="x"))
    execution = await ctx.executions_repo.create(task_id=task.id, project_id=project.id)
    await ctx.executions_repo.update_plan(execution.id, {
        "steps": [{"id": "s1", "step_type": "implementation", "required_capability": "debugging", "input": {"category": "debugging"}}],
    })
    for _ in range(6):
        await ctx.context_metrics_repo.record(
            execution_id=execution.id, step_id="s1", agent_id="agent_x",
            file_paths=["a.py", "b.py", "c.py", "README.md"], bytes_total=400, files_used=["a.py"],
        )

    suggestions = await dispatch("context_optimizer.suggestions", {}, ctx)
    assert len(suggestions) == 1
    assert suggestions[0]["task_category"] == "debugging"
    assert suggestions[0]["suggestion"] == "reduce"


async def test_context_optimizer_suggestions_empty_when_no_data(ctx) -> None:
    assert await dispatch("context_optimizer.suggestions", {}, ctx) == []
