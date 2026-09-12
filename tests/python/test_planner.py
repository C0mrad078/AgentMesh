from __future__ import annotations

from datetime import UTC, datetime

from core.orchestrator.dag import build_execution_layers
from core.orchestrator.intent_analyzer import IntentAnalyzer
from core.orchestrator.models import ComplexityLevel, Intent, RiskLevel
from core.orchestrator.planner import AIPlanner, Planner, RuleBasedPlanner
from core.providers.base import AIRequest, AIResponse, ProviderHealthStatus, TokenUsage
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry
from core.tasks.models import Task, TaskMode


def _task(title: str, description: str = "", *, mode: TaskMode = TaskMode.AUTOMATIC, input: dict | None = None) -> Task:
    now = datetime.now(UTC)
    return Task(
        id="task_1", project_id="proj_1", title=title, description=description, mode=mode,
        input=input or {}, created_at=now, updated_at=now,
    )


def test_simple_task_produces_a_single_step_plan() -> None:
    intent = IntentAnalyzer().analyze(_task("Fix typo"))
    plan = RuleBasedPlanner().create_plan(_task("Fix typo"), intent)
    assert len(plan.steps) == 1
    assert plan.source == "rule_based"


def test_multi_category_task_produces_one_step_per_category() -> None:
    task = _task("Analise a autenticação e corrija vulnerabilidades de segurança")
    intent = IntentAnalyzer().analyze(task)
    assert len(intent.categories) >= 2
    plan = RuleBasedPlanner().create_plan(task, intent)
    assert len(plan.steps) == len(intent.categories)


def test_steps_form_a_valid_dependency_chain() -> None:
    task = _task("Pesquise, implemente e documente uma nova feature de pagamento")
    intent = IntentAnalyzer().analyze(task)
    plan = RuleBasedPlanner().create_plan(task, intent)
    layers = build_execution_layers(plan.steps)
    assert sum(len(layer) for layer in layers) == len(plan.steps)


def test_high_risk_task_gets_an_extra_review_step() -> None:
    task = _task("Corrija o sistema de login")
    intent = Intent(categories=("debugging",), summary="x", risk=RiskLevel.HIGH)
    plan = RuleBasedPlanner().create_plan(task, intent)
    assert any(s.step_type == "review" for s in plan.steps)


def test_low_risk_task_gets_no_extra_review_step() -> None:
    task = _task("Rename a variable")
    intent = Intent(categories=("refactoring",), summary="x", risk=RiskLevel.LOW)
    plan = RuleBasedPlanner().create_plan(task, intent)
    assert not any(s.step_type == "review" for s in plan.steps)


def test_manual_mode_assigns_the_chosen_agent() -> None:
    task = _task("Do X", mode=TaskMode.MANUAL, input={"agent_id": "agent_claude_architect"})
    intent = IntentAnalyzer().analyze(task)
    plan = RuleBasedPlanner().create_plan(task, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].assigned_agent_id == "agent_claude_architect"


def test_pipeline_mode_creates_a_sequential_chain() -> None:
    task = _task(
        "Do X", mode=TaskMode.PIPELINE,
        input={"agent_ids": ["agent_gemini_researcher", "agent_claude_architect", "agent_codex_developer"]},
    )
    intent = IntentAnalyzer().analyze(task)
    plan = RuleBasedPlanner().create_plan(task, intent)
    assert [s.assigned_agent_id for s in plan.steps] == [
        "agent_gemini_researcher", "agent_claude_architect", "agent_codex_developer",
    ]
    assert plan.steps[1].dependencies == (plan.steps[0].id,)
    assert plan.steps[2].dependencies == (plan.steps[1].id,)


def test_pipeline_mode_without_agent_ids_falls_back_to_automatic() -> None:
    task = _task("Do X", mode=TaskMode.PIPELINE, input={})
    intent = IntentAnalyzer().analyze(task)
    plan = RuleBasedPlanner().create_plan(task, intent)
    assert plan.strategy == "automatic"


def test_debate_mode_creates_parallel_candidates_and_a_synthesis_step() -> None:
    task = _task(
        "Do X", mode=TaskMode.DEBATE,
        input={"agent_ids": ["agent_claude_architect", "agent_gemini_researcher", "agent_codex_developer"]},
    )
    intent = IntentAnalyzer().analyze(task)
    plan = RuleBasedPlanner().create_plan(task, intent)

    candidates = [s for s in plan.steps if s.step_type != "synthesis"]
    synthesis = [s for s in plan.steps if s.step_type == "synthesis"]
    assert len(candidates) == 3
    assert all(c.dependencies == () for c in candidates)
    assert len(synthesis) == 1
    assert set(synthesis[0].dependencies) == {c.id for c in candidates}


def test_debate_mode_with_too_few_agents_falls_back_to_automatic() -> None:
    task = _task("Do X", mode=TaskMode.DEBATE, input={"agent_ids": ["agent_claude_architect"]})
    intent = IntentAnalyzer().analyze(task)
    plan = RuleBasedPlanner().create_plan(task, intent)
    assert plan.strategy == "automatic"


def test_consensus_mode_uses_the_same_shape_as_debate() -> None:
    task = _task(
        "Do X", mode=TaskMode.CONSENSUS,
        input={"agent_ids": ["agent_claude_architect", "agent_gemini_researcher"]},
    )
    intent = IntentAnalyzer().analyze(task)
    plan = RuleBasedPlanner().create_plan(task, intent)
    assert plan.strategy == "consensus"
    assert any(s.step_type == "synthesis" for s in plan.steps)


async def test_planner_facade_skips_ai_for_low_complexity() -> None:
    task = _task("Fix typo")
    intent = Intent(categories=("coding",), summary="x", complexity=ComplexityLevel.LOW)

    class _ExplodingAIPlanner:
        async def create_plan(self, task, intent):
            raise AssertionError("AIPlanner should not be called for low-complexity tasks")

    planner = Planner(ai_planner=_ExplodingAIPlanner())  # type: ignore[arg-type]
    plan = await planner.create_plan(task, intent)
    assert plan.source == "rule_based"


class _StructuredFakeProvider:
    """Returns a valid plan on the first call, every time -- used to test the
    AIPlanner's happy path without a real provider."""

    name = "fake"

    def __init__(self, structured_output: dict | None) -> None:
        self._structured_output = structured_output

    async def execute(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            content="", provider=self.name, model="fake-model", finish_reason="stop",
            usage=TokenUsage(input_tokens=10, output_tokens=10), duration_seconds=0.01,
            structured_output=self._structured_output,
        )

    async def stream(self, request):
        yield ""

    async def health_check(self) -> ProviderHealthStatus:
        return ProviderHealthStatus.ONLINE

    async def list_models(self) -> list[str]:
        return ["fake-model"]

    async def cancel(self, execution_id: str) -> None:
        return None


def _ai_planner_with(structured_output: dict | None) -> AIPlanner:
    from core.providers.registry import DEFAULT_MODELS, ModelInfo

    registry = ModelRegistry(
        [*DEFAULT_MODELS, ModelInfo(
            provider="fake", model_id="fake-model", display_name="Fake",
            capabilities=("planning",), supports_structured_output=True,
        )]
    )
    pool = ProviderPool()
    pool.register(_StructuredFakeProvider(structured_output))
    health = ProviderHealthMonitor()
    return AIPlanner(registry, pool, health)


async def test_ai_planner_uses_valid_structured_output() -> None:
    valid_plan = {
        "goal": "do it",
        "steps": [
            {"id": "a", "description": "step a", "type": "analysis", "required_capability": "analysis"},
            {"id": "b", "description": "step b", "type": "implementation", "required_capability": "coding", "dependencies": ["a"]},
        ],
    }
    planner = _ai_planner_with(valid_plan)
    task = _task("Do something medium complexity here please")
    intent = Intent(categories=("coding",), summary="x", complexity=ComplexityLevel.MEDIUM)

    plan = await planner.create_plan(task, intent)
    assert plan.source == "ai"
    assert len(plan.steps) == 2
    assert plan.steps[1].dependencies == (plan.steps[0].id,)


async def test_ai_planner_falls_back_to_rule_based_on_invalid_output() -> None:
    planner = _ai_planner_with({"not": "a valid plan"})
    task = _task("Fix the bug in the login flow")
    intent = Intent(categories=("debugging",), summary="x", complexity=ComplexityLevel.MEDIUM)

    plan = await planner.create_plan(task, intent)
    assert plan.source == "rule_based"


async def test_ai_planner_falls_back_when_plan_has_a_cycle() -> None:
    cyclic_plan = {
        "goal": "do it",
        "steps": [
            {"id": "a", "description": "a", "type": "analysis", "required_capability": "analysis", "dependencies": ["b"]},
            {"id": "b", "description": "b", "type": "analysis", "required_capability": "analysis", "dependencies": ["a"]},
        ],
    }
    planner = _ai_planner_with(cyclic_plan)
    task = _task("Do something")
    intent = Intent(categories=("analysis",), summary="x", complexity=ComplexityLevel.MEDIUM)
    plan = await planner.create_plan(task, intent)
    assert plan.source == "rule_based"


async def test_ai_planner_falls_back_when_no_provider_configured() -> None:
    registry = ModelRegistry([])
    pool = ProviderPool()
    health = ProviderHealthMonitor()
    planner = AIPlanner(registry, pool, health)
    task = _task("Do something")
    intent = Intent(categories=("analysis",), summary="x", complexity=ComplexityLevel.MEDIUM)
    plan = await planner.create_plan(task, intent)
    assert plan.source == "rule_based"
