from __future__ import annotations

from core.agents.registry import AgentRegistry
from core.database.connection import Database
from core.database.repositories.learned_rules_repo import LearnedRulesRepository
from core.database.repositories.model_performance_repo import ModelPerformanceRepository
from core.learning.model_performance import ModelPerformanceTracker
from core.learning.rule_resolver import RuleResolver
from core.orchestrator.models import PlanStep, RiskLevel
from core.orchestrator.router import Router
from core.providers.circuit_breaker import CircuitBreaker
from core.providers.health import ProviderHealthMonitor
from core.providers.mock_provider import MockProvider
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry


def _step(capability: str = "coding") -> PlanStep:
    return PlanStep(id="step_1", name="test", description="test", required_capability=capability)


async def _record(tracker: ModelPerformanceTracker, *, agent_id: str, verified_rate_successes: int, total: int) -> None:
    for i in range(total):
        await tracker.record_execution_outcome(
            provider="mock", model="mock-model", agent_id=agent_id, task_category="general", risk="low",
            success=True, verified_success=i < verified_rate_successes, retried=False, review_rejected=False,
            latency_seconds=1.0, input_tokens=10, output_tokens=10, cost_usd=0.001, iterations=0,
        )


def _agents() -> AgentRegistry:
    return AgentRegistry([
        a for a in AgentRegistry().list_agents(only_active=False) if a.id in ("agent_generalist", "agent_coder")
    ])


async def test_router_prefers_the_agent_with_a_better_verified_track_record(tmp_db: Database) -> None:
    tracker = ModelPerformanceTracker(ModelPerformanceRepository(tmp_db))
    # agent_coder: 19/20 verified success. agent_generalist: 4/20.
    await _record(tracker, agent_id="agent_coder", verified_rate_successes=19, total=20)
    await _record(tracker, agent_id="agent_generalist", verified_rate_successes=4, total=20)

    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker())

    # Both agents map to the same mock model, so without history they'd be
    # scored identically by capability/availability/cost alone --
    # `agent_coder`'s much better verified track record should win.
    router = Router(_agents(), ModelRegistry(), pool, health, performance_tracker=tracker)
    decision = await router.route(_step("coding"), risk=RiskLevel.HIGH)  # HIGH disables exploration jitter
    assert decision.agent_id == "agent_coder"


async def test_small_sample_history_does_not_override_capability_requirements(tmp_db: Database) -> None:
    tracker = ModelPerformanceTracker(ModelPerformanceRepository(tmp_db))
    # A single lucky observation for the agent that does NOT match the
    # step's capability should never make the Router pick it anyway --
    # capability filtering happens before scoring, so this only guards
    # against the historical term dominating among *already qualified*
    # candidates when the sample is tiny.
    await _record(tracker, agent_id="agent_generalist", verified_rate_successes=1, total=1)

    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker())
    router = Router(_agents(), ModelRegistry(), pool, health, performance_tracker=tracker)

    decision = await router.route(_step("coding"), risk=RiskLevel.HIGH)
    agent = AgentRegistry().get(decision.agent_id)
    assert any(c.name == "coding" for c in agent.capabilities)


async def test_a_single_great_execution_does_not_dominate_over_a_larger_worse_sample(tmp_db: Database) -> None:
    tracker = ModelPerformanceTracker(ModelPerformanceRepository(tmp_db))
    # agent_generalist: 1/1 (100%, but tiny sample). agent_coder: 15/20 (75%, solid sample).
    await _record(tracker, agent_id="agent_generalist", verified_rate_successes=1, total=1)
    await _record(tracker, agent_id="agent_coder", verified_rate_successes=15, total=20)

    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker())
    router = Router(_agents(), ModelRegistry(), pool, health, performance_tracker=tracker)

    decision = await router.route(_step("coding"), risk=RiskLevel.HIGH)
    assert decision.agent_id == "agent_coder"


async def test_router_without_performance_tracker_behaves_exactly_as_before(tmp_db: Database) -> None:
    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker())
    router = Router(_agents(), ModelRegistry(), pool, health)
    decision = await router.route(_step("coding"))
    assert decision.agent_id == "agent_coder"  # only capability-matching agent


async def test_learned_rule_avoiding_an_agent_lowers_its_score(tmp_db: Database) -> None:
    rules_repo = LearnedRulesRepository(tmp_db)
    rule = await rules_repo.create(
        title="Evitar agent_coder para debugging trivial", category="agent_selection", rule_text="x",
        scope_type="global", scope_value=None, priority="normal", confidence=0.9, observations=10,
        successes=9, failures=1, distinct_projects=["p1"], status="active", origin="learning_engine",
    )
    await rules_repo.update_action(rule["id"], {"effect": "avoid_agent", "agent_id": "agent_coder", "magnitude": 1.0})

    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker())
    resolver = RuleResolver(rules_repo)
    router = Router(_agents(), ModelRegistry(), pool, health, rule_resolver=resolver)

    # agent_coder is still the only capability match, so it must still win
    # (a learned rule can only adjust score among viable candidates, never
    # remove the only option) -- but its score should reflect the penalty.
    with_rule = await router.route(_step("coding"))
    router_without_rule = Router(_agents(), ModelRegistry(), pool, health)
    without_rule = await router_without_rule.route(_step("coding"))
    assert with_rule.agent_id == "agent_coder"
    assert with_rule.score < without_rule.score
