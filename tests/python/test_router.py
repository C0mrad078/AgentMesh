from __future__ import annotations

import pytest
from core.agents.registry import AgentRegistry
from core.orchestrator.models import PlanStep, RiskLevel
from core.orchestrator.router import Router, RoutingWeights
from core.providers.circuit_breaker import CircuitBreaker
from core.providers.health import ProviderHealthMonitor
from core.providers.mock_provider import MockProvider
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry
from core.utils.errors import NotFoundError, ProviderTimeoutError


def _step(capability: str, *, step_type: str = "implementation", assigned_agent_id: str | None = None) -> PlanStep:
    return PlanStep(
        id="step_1", name="test", description="test step", required_capability=capability,
        step_type=step_type, assigned_agent_id=assigned_agent_id,
    )


def _make_router(*, registered_providers: tuple[str, ...] = ("mock",), weights: RoutingWeights | None = None) -> Router:
    pool = ProviderPool()
    for name in registered_providers:
        assert name == "mock", "only MockProvider is available without real credentials in tests"
        pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker())
    return Router(AgentRegistry(), ModelRegistry(), pool, health, weights)


async def test_coding_routes_to_a_coding_capable_agent() -> None:
    router = _make_router()
    decision = await router.route(_step("coding"))
    agent = AgentRegistry().get(decision.agent_id)
    assert agent is not None
    assert any(c.name == "coding" for c in agent.capabilities)


async def test_no_candidates_raises_not_found() -> None:
    router = _make_router(registered_providers=())
    with pytest.raises(NotFoundError):
        await router.route(_step("coding"))


async def test_unregistered_provider_is_excluded() -> None:
    # agent_codex_developer needs "openai"; only mock is registered, so it
    # must never be selected even though its capability matches.
    router = _make_router(registered_providers=("mock",))
    decision = await router.route(_step("coding"))
    assert decision.provider == "mock"


async def test_explicit_assigned_agent_overrides_capability_routing() -> None:
    router = _make_router(registered_providers=("mock",))
    decision = await router.route(_step("general", assigned_agent_id="agent_generalist"))
    assert decision.agent_id == "agent_generalist"


async def test_assigned_agent_not_registered_raises_not_found() -> None:
    router = _make_router(registered_providers=("mock",))
    with pytest.raises(NotFoundError):
        await router.route(_step("coding", assigned_agent_id="agent_codex_developer"))


async def test_exclude_agent_ids_removes_candidate_for_fallback() -> None:
    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker())
    registry = AgentRegistry(
        [
            a for a in AgentRegistry().list_agents(only_active=False)
            if a.id in ("agent_generalist", "agent_coder")
        ]
    )
    router = Router(registry, ModelRegistry(), pool, health)

    first = await router.route(_step("coding"))
    assert first.agent_id == "agent_coder"

    second = await router.route(_step("coding"), exclude_agent_ids=frozenset({"agent_coder"}))
    assert second.agent_id != "agent_coder"


async def test_degraded_provider_scores_lower_than_healthy_one() -> None:
    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker())
    router = Router(AgentRegistry(), ModelRegistry(), pool, health)

    step = _step("coding")
    baseline = await router.route(step)

    await health.report_failure("mock", ProviderTimeoutError("slow"))
    degraded = await router.route(step)
    assert degraded.score < baseline.score


async def test_risk_review_bonus_favors_review_step_scoring() -> None:
    router = _make_router()
    normal_step = _step("analysis", step_type="implementation")
    review_step = _step("analysis", step_type="review")

    normal_decision = await router.route(normal_step, risk=RiskLevel.HIGH)
    review_decision = await router.route(review_step, risk=RiskLevel.HIGH)
    assert review_decision.score > normal_decision.score


async def test_reason_is_human_readable_and_non_empty() -> None:
    router = _make_router()
    decision = await router.route(_step("coding"))
    assert decision.reason
    assert decision.agent_id in decision.reason or "selecionado" in decision.reason.lower()


async def test_alternatives_exclude_the_winner() -> None:
    router = _make_router()
    decision = await router.route(_step("general"))
    assert decision.agent_id not in decision.alternatives
