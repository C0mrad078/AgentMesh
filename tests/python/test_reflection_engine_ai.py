"""Tests for the (optional, cost-bounded) AI-assisted half of the
Reflection Engine -- see `tests/python/test_reflection_engine.py` for the
deterministic-only coverage that runs regardless of whether a provider is
available. `MockProvider` never populates `structured_output`, so these
use a small fake structured provider (same pattern as
`tests/python/test_planner.py::_StructuredFakeProvider`) instead.
"""

from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.context_metrics_repo import ContextMetricsRepository
from core.database.repositories.executions_repo import ExecutionsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.routing_decisions_repo import RoutingDecisionsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.database.repositories.tool_calls_repo import ToolCallsRepository
from core.database.repositories.usage_metrics_repo import UsageMetricsRepository
from core.learning.reflection_engine import ReflectionEngine
from core.orchestrator.models import ExecutionStatus
from core.projects.models import ProjectCreate
from core.providers.base import AIResponse, ProviderHealthStatus, TokenUsage
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import DEFAULT_MODELS, ModelInfo, ModelRegistry
from core.tasks.models import TaskCreate, TaskStatus


class _StructuredFakeProvider:
    name = "fake_reflect"

    def __init__(self, structured_output: dict | None, *, cost_per_call: float = 0.0001) -> None:
        self._structured_output = structured_output
        self.calls = 0
        self._cost_per_call = cost_per_call

    async def execute(self, request):
        self.calls += 1
        return AIResponse(
            content="", provider=self.name, model="fake-analysis-model", finish_reason="stop",
            usage=TokenUsage(input_tokens=50, output_tokens=50), duration_seconds=0.01,
            structured_output=self._structured_output,
        )

    async def stream(self, request):
        yield ""

    async def health_check(self) -> ProviderHealthStatus:
        return ProviderHealthStatus.ONLINE

    async def list_models(self) -> list[str]:
        return ["fake-analysis-model"]

    async def cancel(self, execution_id: str) -> None:
        return None


async def _make_execution(db: Database, *, total_cost_usd: float) -> str:
    project = await ProjectsRepository(db).create(ProjectCreate(name="AI Reflection Test"))
    task = await TasksRepository(db).create(TaskCreate(project_id=project.id, title="x"))
    execution = await ExecutionsRepository(db).create(task_id=task.id, project_id=project.id)
    plan = {
        "strategy": "automatic", "source": "rule_based", "playbook_version_id": None,
        "intent": {"categories": ["debugging"], "risk": "high", "complexity": "high"},
        "steps": [{"id": "s1", "step_type": "implementation", "required_capability": "debugging", "dependencies": []}],
    }
    await ExecutionsRepository(db).update_plan(execution.id, plan)
    await ExecutionsRepository(db).update_status(execution.id, ExecutionStatus.FAILED, completed=True)
    await TasksRepository(db).update_status(
        task.id, TaskStatus.FAILED,
        result={"verification": {"passed": False, "reasons": ["x"], "checks": []}, "total_cost_usd": total_cost_usd, "total_tokens": 500},
    )
    return execution.id


def _real_engine_deps(db: Database, registry: ModelRegistry, pool: ProviderPool) -> ReflectionEngine:
    return ReflectionEngine(
        ExecutionsRepository(db), TasksRepository(db), RoutingDecisionsRepository(db),
        ToolCallsRepository(db), UsageMetricsRepository(db), ContextMetricsRepository(db),
        registry, pool, ProviderHealthMonitor(),
    )


async def test_ai_narrative_is_used_when_the_execution_cost_justifies_it(tmp_db: Database) -> None:
    fake_output = {
        "overall_score": 0.4, "narrative": "Codex falhou porque faltou contexto de tipos.",
        "additional_problems": ["Contexto insuficiente enviado ao Codex."],
        "improvement_candidates": [
            {"category": "context", "title": "Enviar arquivo de tipos", "rule_text": "Incluir o arquivo de tipos relevante em debugging de TypeScript."},
        ],
    }
    provider = _StructuredFakeProvider(fake_output)
    registry = ModelRegistry([
        *DEFAULT_MODELS,
        ModelInfo(provider="fake_reflect", model_id="fake-analysis-model", display_name="Fake",
                  capabilities=("analysis",), supports_structured_output=True),
    ])
    pool = ProviderPool()
    pool.register(provider)
    engine = _real_engine_deps(tmp_db, registry, pool)

    execution_id = await _make_execution(tmp_db, total_cost_usd=1.0)
    reflection = await engine.reflect(execution_id)

    assert provider.calls == 1
    assert reflection.ai_narrative == fake_output["narrative"]
    assert reflection.overall_score == 0.4
    assert "Contexto insuficiente enviado ao Codex." in reflection.problems
    assert any(c.title == "Enviar arquivo de tipos" for c in reflection.improvement_candidates)


async def test_ai_reflection_is_skipped_for_trivially_cheap_executions(tmp_db: Database) -> None:
    provider = _StructuredFakeProvider({"overall_score": 0.9, "narrative": "should not be used"})
    registry = ModelRegistry([
        *DEFAULT_MODELS,
        ModelInfo(provider="fake_reflect", model_id="fake-analysis-model", display_name="Fake",
                  capabilities=("analysis",), supports_structured_output=True),
    ])
    pool = ProviderPool()
    pool.register(provider)
    engine = _real_engine_deps(tmp_db, registry, pool)

    execution_id = await _make_execution(tmp_db, total_cost_usd=0.0001)
    reflection = await engine.reflect(execution_id)

    assert provider.calls == 0
    assert reflection.ai_narrative is None


async def test_invalid_ai_output_falls_back_to_deterministic_only(tmp_db: Database) -> None:
    provider = _StructuredFakeProvider({"narrative": "missing overall_score field"})
    registry = ModelRegistry([
        *DEFAULT_MODELS,
        ModelInfo(provider="fake_reflect", model_id="fake-analysis-model", display_name="Fake",
                  capabilities=("analysis",), supports_structured_output=True),
    ])
    pool = ProviderPool()
    pool.register(provider)
    engine = _real_engine_deps(tmp_db, registry, pool)

    execution_id = await _make_execution(tmp_db, total_cost_usd=1.0)
    reflection = await engine.reflect(execution_id)

    assert reflection.ai_narrative is None
    assert reflection.overall_score < 0.3  # deterministic score for a failed execution
