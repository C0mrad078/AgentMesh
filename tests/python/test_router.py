from __future__ import annotations

import pytest
from core.agents.models import Agent, AgentCapability, AgentPermissions
from core.agents.registry import AgentRegistry
from core.orchestrator.models import PlanStep, RiskLevel
from core.orchestrator.router import Router, RoutingWeights
from core.providers.circuit_breaker import CircuitBreaker
from core.providers.health import ProviderHealthMonitor
from core.providers.mock_provider import MockProvider
from core.providers.pool import ProviderPool
from core.providers.registry import ModelInfo, ModelRegistry
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


def _fallback_preference_setup() -> tuple[Router, str, str]:
    """Two equally-capable agents on two distinct (mock, but distinctly
    named) providers -- neither has any other scoring edge over the
    other, so any score difference between them is attributable only to
    `preferred_fallback_providers`."""
    provider_a = MockProvider()
    provider_a.name = "provider_a"  # test-only rename so the pool sees two distinct providers
    provider_b = MockProvider()
    provider_b.name = "provider_b"
    pool = ProviderPool()
    pool.register(provider_a)
    pool.register(provider_b)

    models = ModelRegistry(
        models=[
            ModelInfo(
                provider="provider_a", model_id="default", display_name="A",
                capabilities=("testing",), priority=1,
            ),
            ModelInfo(
                provider="provider_b", model_id="default", display_name="B",
                capabilities=("testing",), priority=1,
            ),
        ]
    )
    agent_a = Agent(
        id="agent_test_a", name="Agent A", provider="provider_a", model="default",
        capabilities=[AgentCapability(name="testing", description="")],
        permissions=AgentPermissions(),
    )
    agent_b = Agent(
        id="agent_test_b", name="Agent B", provider="provider_b", model="default",
        capabilities=[AgentCapability(name="testing", description="")],
        permissions=AgentPermissions(),
    )
    registry = AgentRegistry([agent_a, agent_b])
    health = ProviderHealthMonitor(CircuitBreaker())
    router = Router(registry, models, pool, health)
    return router, agent_a.id, agent_b.id


async def test_fallback_preference_bonus_favors_the_declared_provider() -> None:
    router, agent_a_id, agent_b_id = _fallback_preference_setup()
    step = _step("testing")

    baseline = await router.route(step)
    assert baseline.agent_id == agent_a_id  # tie-break: registration order, no bonus in play

    preferred = await router.route(step, preferred_fallback_providers=frozenset({"provider_b"}))
    assert preferred.agent_id == agent_b_id
    assert "fallback preferido" in preferred.reason


async def test_fallback_preference_bonus_is_absent_by_default() -> None:
    router, agent_a_id, _agent_b_id = _fallback_preference_setup()
    decision = await router.route(_step("testing"))
    assert "fallback preferido" not in decision.reason
    assert decision.agent_id == agent_a_id
