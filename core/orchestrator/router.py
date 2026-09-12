"""AI Router.

Decides which agent (and, through it, which provider+model) executes each
plan step. This is not a fixed lookup table (`coding -> Codex`) -- every
candidate agent capable of the step's `required_capability` is scored on
multiple signals, and the highest-scoring one wins:

    score = capability_match
          + availability (provider health)
          + priority (model's configured priority)
          + structured_output bonus
          - cost_penalty (proportional to the model's per-call cost estimate)
          - failure_penalty (provider is rate-limited/unavailable)

Stage 2 has no execution history yet (that is Stage 3's Reflection Engine),
so `historical_quality` is a fixed, configurable weight rather than a
learned one -- the hook exists (`RoutingWeights.historical_quality`) but is
inert until there is data to feed it.

A short, human-readable `reason` is always recorded alongside the decision
(persisted via `core.database.repositories.routing_decisions_repo`) -- e.g.
"Claude Architect selecionado porque a etapa envolve arquitetura e possui
risco alto." This is a summary of the decision, not the model's reasoning.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from core.agents.models import Agent
from core.agents.registry import AgentRegistry
from core.orchestrator.models import PlanStep, RiskLevel, RoutingDecision
from core.providers.base import ProviderHealthStatus
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelInfo, ModelRegistry
from core.utils.errors import NotFoundError

_FALLBACK_AGENT_ID = "agent_generalist"


@dataclass(frozen=True)
class RoutingWeights:
    capability_match: float = 10.0
    historical_quality: float = 0.0
    availability: float = 5.0
    structured_output_bonus: float = 1.5
    priority_weight: float = 1.0
    cost_penalty: float = 0.5
    failure_penalty: float = 8.0
    risk_review_bonus: float = 3.0


@dataclass(frozen=True)
class _Candidate:
    agent: Agent
    model: ModelInfo
    score: float
    reason: str


class Router:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        model_registry: ModelRegistry,
        provider_pool: ProviderPool,
        health_monitor: ProviderHealthMonitor,
        weights: RoutingWeights | None = None,
    ) -> None:
        self._agents = agent_registry
        self._models = model_registry
        self._pool = provider_pool
        self._health = health_monitor
        self._weights = weights or RoutingWeights()

    def route(
        self,
        step: PlanStep,
        *,
        risk: RiskLevel = RiskLevel.LOW,
        exclude_agent_ids: frozenset[str] = frozenset(),
    ) -> RoutingDecision:
        candidates = self._build_candidates(step, risk=risk, exclude_agent_ids=exclude_agent_ids)
        if not candidates:
            raise NotFoundError(
                f"No agent/provider/model combination is available for step '{step.id}' "
                f"(capability='{step.required_capability}').",
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]
        alternatives = tuple(f"{c.agent.id}:{c.model.model_id}" for c in candidates[1:4])

        return RoutingDecision(
            step_id=step.id,
            agent_id=best.agent.id,
            provider=best.agent.provider,
            model=best.model.model_id,
            reason=best.reason,
            score=best.score,
            alternatives=alternatives,
        )

    def _build_candidates(
        self, step: PlanStep, *, risk: RiskLevel, exclude_agent_ids: frozenset[str]
    ) -> list[_Candidate]:
        if step.assigned_agent_id:
            explicit = self._agents.get(step.assigned_agent_id)
            pool = [explicit] if explicit else []
            candidates = self._score_pool(pool, step, risk=risk, exclude_agent_ids=exclude_agent_ids)
            return candidates

        pool = self._agents.find_by_capability(step.required_capability)
        candidates = self._score_pool(pool, step, risk=risk, exclude_agent_ids=exclude_agent_ids)
        if candidates:
            return candidates

        # No usable candidate matched the capability directly (either none
        # exist, or every match was excluded/unregistered/model-less) --
        # only *then* fall back to the generalist, so a fallback/retry that
        # excludes the primary agent still has somewhere to go.
        fallback = self._agents.get(_FALLBACK_AGENT_ID)
        return self._score_pool([fallback] if fallback else [], step, risk=risk, exclude_agent_ids=exclude_agent_ids)

    def _score_pool(
        self,
        pool: Iterable[Agent | None],
        step: PlanStep,
        *,
        risk: RiskLevel,
        exclude_agent_ids: frozenset[str],
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for agent in pool:
            if agent is None or agent.id in exclude_agent_ids:
                continue
            if not self._pool.is_registered(agent.provider):
                continue
            model = self._resolve_model(agent, step.required_capability)
            if model is None:
                continue
            score, reason = self._score(agent, model, step, risk=risk)
            candidates.append(_Candidate(agent=agent, model=model, score=score, reason=reason))
        return candidates

    def _resolve_model(self, agent: Agent, capability: str) -> ModelInfo | None:
        exact = self._models.get(agent.provider, agent.model)
        if exact is not None and exact.enabled:
            return exact
        by_capability = [m for m in self._models.for_provider(agent.provider) if capability in m.capabilities]
        if by_capability:
            return by_capability[0]
        provider_models = self._models.for_provider(agent.provider)
        return provider_models[0] if provider_models else None

    def _score(
        self, agent: Agent, model: ModelInfo, step: PlanStep, *, risk: RiskLevel
    ) -> tuple[float, str]:
        w = self._weights
        score = 0.0
        reasons: list[str] = []

        if step.required_capability in model.capabilities:
            score += w.capability_match
            reasons.append(f"a etapa envolve {step.required_capability}")

        health = self._health.status_of(agent.provider)
        if health in (ProviderHealthStatus.ONLINE, ProviderHealthStatus.UNKNOWN):
            score += w.availability
        elif health == ProviderHealthStatus.DEGRADED:
            score += w.availability * 0.3
            reasons.append("provider degradado")
        else:
            score -= w.failure_penalty
            reasons.append(f"provider {health.value}")

        if model.supports_structured_output:
            score += w.structured_output_bonus

        score += w.priority_weight * (model.priority / 10.0)

        estimated_cost = model.estimate_cost_usd(1000, 500)
        score -= w.cost_penalty * estimated_cost

        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL) and step.step_type == "review":
            score += w.risk_review_bonus
            reasons.append("risco alto exige revisão")

        reason_text = ", ".join(reasons) if reasons else "melhor opção disponível para a etapa"
        return score, f"{agent.name} selecionado porque {reason_text}."
