from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.context_metrics_repo import ContextMetricsRepository
from core.database.repositories.executions_repo import ExecutionsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.routing_decisions_repo import RoutingDecisionsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.database.repositories.tool_calls_repo import ToolCallsRepository
from core.database.repositories.usage_metrics_repo import UsageMetricsRepository
from core.learning.models import FailureCategory, ReflectionDepth
from core.learning.reflection_engine import ReflectionEngine
from core.orchestrator.models import ExecutionStatus, RoutingDecision
from core.projects.models import ProjectCreate
from core.providers.circuit_breaker import CircuitBreaker
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry
from core.tasks.models import TaskCreate, TaskStatus


def _engine(db: Database) -> ReflectionEngine:
    return ReflectionEngine(
        ExecutionsRepository(db), TasksRepository(db), RoutingDecisionsRepository(db),
        ToolCallsRepository(db), UsageMetricsRepository(db), ContextMetricsRepository(db),
        ModelRegistry(), ProviderPool(), ProviderHealthMonitor(CircuitBreaker()),
    )


async def _make_execution(
    db: Database, *, plan: dict, task_status: TaskStatus, result: dict, execution_status: ExecutionStatus,
) -> str:
    project = await ProjectsRepository(db).create(ProjectCreate(name="Reflection Test"))
    task = await TasksRepository(db).create(TaskCreate(project_id=project.id, title="x"))
    execution = await ExecutionsRepository(db).create(task_id=task.id, project_id=project.id)
    await ExecutionsRepository(db).update_plan(execution.id, plan)
    await ExecutionsRepository(db).update_status(execution.id, execution_status, completed=True)
    await TasksRepository(db).update_status(task.id, task_status, result=result)
    return execution.id


def _plan(*, strategy: str = "automatic", steps: list[dict] | None = None, risk: str = "low") -> dict:
    return {
        "strategy": strategy, "source": "rule_based", "playbook_version_id": None,
        "intent": {"categories": ["debugging"], "risk": risk, "complexity": "medium"},
        "steps": steps or [{"id": "s1", "step_type": "implementation", "required_capability": "debugging", "dependencies": []}],
    }


async def test_a_clean_success_gets_a_light_reflection_with_a_high_score(tmp_db: Database) -> None:
    execution_id = await _make_execution(
        tmp_db, plan=_plan(), task_status=TaskStatus.COMPLETED,
        result={"verification": {"passed": True, "reasons": [], "checks": []}, "total_cost_usd": 0.001, "total_tokens": 50},
        execution_status=ExecutionStatus.COMPLETED,
    )
    reflection = await _engine(tmp_db).reflect(execution_id)
    assert reflection.depth == ReflectionDepth.LIGHT
    assert reflection.overall_score > 0.7
    assert reflection.failure_category == FailureCategory.NONE
    assert reflection.findings  # deterministic findings are always produced


async def test_a_failed_verification_gets_a_full_reflection_with_a_low_score(tmp_db: Database) -> None:
    execution_id = await _make_execution(
        tmp_db, plan=_plan(), task_status=TaskStatus.FAILED,
        result={"verification": {"passed": False, "reasons": ["step failed"], "checks": []}, "total_cost_usd": 0.01, "total_tokens": 100},
        execution_status=ExecutionStatus.FAILED,
    )
    reflection = await _engine(tmp_db).reflect(execution_id)
    assert reflection.depth == ReflectionDepth.FULL
    assert reflection.overall_score < 0.3


async def test_partial_success_is_classified_distinctly_from_total_failure(tmp_db: Database) -> None:
    execution_id = await _make_execution(
        tmp_db, plan=_plan(), task_status=TaskStatus.PARTIAL,
        result={"verification": {"passed": False, "reasons": ["gate failed"], "checks": []}, "total_cost_usd": 0.01, "total_tokens": 100},
        execution_status=ExecutionStatus.COMPLETED,
    )
    reflection = await _engine(tmp_db).reflect(execution_id)
    partial_score = reflection.overall_score

    execution_id_2 = await _make_execution(
        tmp_db, plan=_plan(), task_status=TaskStatus.FAILED,
        result={"verification": {"passed": False, "reasons": ["gate failed"], "checks": []}, "total_cost_usd": 0.01, "total_tokens": 100},
        execution_status=ExecutionStatus.FAILED,
    )
    failed_score = await _engine(tmp_db).reflect(execution_id_2)
    assert partial_score > failed_score.overall_score


async def test_excessive_retries_are_flagged_as_a_problem(tmp_db: Database) -> None:
    execution_id = await _make_execution(
        tmp_db, plan=_plan(), task_status=TaskStatus.COMPLETED,
        result={"verification": {"passed": True, "reasons": [], "checks": []}, "total_cost_usd": 0.01, "total_tokens": 100},
        execution_status=ExecutionStatus.COMPLETED,
    )
    await UsageMetricsRepository(tmp_db).record(
        execution_id=execution_id, step_id="s1", agent_id="agent_x", provider="mock", model="m",
        input_tokens=10, output_tokens=10, estimated_cost_usd=0.01, duration_seconds=1.0, success=True,
        retries=3,
    )
    reflection = await _engine(tmp_db).reflect(execution_id)
    assert any("retries" in p.lower() for p in reflection.problems)
    assert reflection.depth == ReflectionDepth.FULL  # excessive retries escalate depth


async def test_multiple_providers_used_escalates_to_full_depth(tmp_db: Database) -> None:
    execution_id = await _make_execution(
        tmp_db, plan=_plan(), task_status=TaskStatus.COMPLETED,
        result={"verification": {"passed": True, "reasons": [], "checks": []}, "total_cost_usd": 0.01, "total_tokens": 100},
        execution_status=ExecutionStatus.COMPLETED,
    )
    routing_repo = RoutingDecisionsRepository(tmp_db)
    await routing_repo.record(execution_id, RoutingDecision(step_id="s1", agent_id="a1", provider="anthropic", model="m1", reason="x"))
    await routing_repo.record(execution_id, RoutingDecision(step_id="s2", agent_id="a2", provider="openai", model="m2", reason="x"))

    reflection = await _engine(tmp_db).reflect(execution_id)
    assert reflection.depth == ReflectionDepth.FULL


async def test_sequential_independent_categories_suggest_a_parallelization_candidate(tmp_db: Database) -> None:
    steps = [
        {"id": "s1", "step_type": "implementation", "required_capability": "security", "dependencies": []},
        {"id": "s2", "step_type": "implementation", "required_capability": "documentation", "dependencies": ["s1"]},
    ]
    execution_id = await _make_execution(
        tmp_db, plan=_plan(steps=steps), task_status=TaskStatus.COMPLETED,
        result={"verification": {"passed": True, "reasons": [], "checks": []}, "total_cost_usd": 0.01, "total_tokens": 100},
        execution_status=ExecutionStatus.COMPLETED,
    )
    reflection = await _engine(tmp_db).reflect(execution_id)
    categories = {c.category.value for c in reflection.improvement_candidates}
    assert "planning" in categories


async def test_budget_failure_is_classified_correctly(tmp_db: Database) -> None:
    execution_id = await _make_execution(
        tmp_db,
        plan={
            **_plan(),
            "steps": [{"id": "s1", "step_type": "implementation", "required_capability": "debugging", "dependencies": [], "error": {"type": "budget_exceeded"}}],
        },
        task_status=TaskStatus.FAILED,
        result={"verification": {"passed": False, "reasons": ["budget exceeded"], "checks": []}, "total_cost_usd": 0.01, "total_tokens": 100},
        execution_status=ExecutionStatus.FAILED,
    )
    reflection = await _engine(tmp_db).reflect(execution_id)
    assert reflection.failure_category == FailureCategory.BUDGET_FAILURE


async def test_cancelled_execution_is_classified_as_user_cancelled(tmp_db: Database) -> None:
    execution_id = await _make_execution(
        tmp_db, plan=_plan(), task_status=TaskStatus.CANCELLED,
        result={"verification": {"passed": False, "reasons": [], "checks": []}, "total_cost_usd": 0.0, "total_tokens": 0},
        execution_status=ExecutionStatus.CANCELLED,
    )
    reflection = await _engine(tmp_db).reflect(execution_id)
    assert reflection.failure_category == FailureCategory.USER_CANCELLED
