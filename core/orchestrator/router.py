"""AI Router.

Decides which agent (and, through it, which provider+model) executes each
plan step. This is not a fixed lookup table (`coding -> Codex`) -- every
candidate agent capable of the step's `required_capability` is scored on
multiple signals, and the highest-scoring one wins:

    score = capability_match
          + historical_verified_success (Stage 3, shrunk toward neutral
            for small samples -- see `core.learning.model_performance`)
          + learned_rule_adjustment (Stage 3 -- see `core.learning.rule_resolver`)
          + availability (provider health)
          + priority (model's configured priority)
          + structured_output bonus
          + exploration jitter (Stage 3, low-risk only, damped as
            observations accumulate -- keeps the Router from permanently
            fixating on whichever model happened to look best early on)
          - cost_penalty (proportional to the model's per-call cost estimate)
          - failure_penalty (provider is rate-limited/unavailable)

`historical_quality`/exploration only activate once `performance_tracker`/
`rule_resolver` are actually wired in (see `core.bridge.context`); every
call site that constructs a `Router` without them (all of Stage 1/2's
tests) gets byte-identical scoring to before -- this is deliberate, so
"aprendizado não deve dominar" holds even in the degenerate case of zero
history, and so Stage 2's Router test suite needed no changes.

A short, human-readable `reason` is always recorded alongside the decision
(persisted via `core.database.repositories.routing_decisions_repo`) -- e.g.
"Claude Architect selecionado porque a etapa envolve arquitetura e possui
risco alto." This is a summary of the decision, not the model's reasoning.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from core.agents.models import Agent
from core.agents.registry import AgentRegistry
from core.learning.model_performance import ModelPerformanceTracker
from core.learning.rule_resolver import RuleResolver
from core.orchestrator.models import PlanStep, RiskLevel, RoutingDecision
from core.providers.base import ProviderHealthStatus
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelInfo, ModelRegistry
from core.utils.errors import NotFoundError

_FALLBACK_AGENT_ID = "agent_generalist"
_MIN_OBSERVATIONS_FOR_FULL_WEIGHT = 10.0


@dataclass(frozen=True)
class RoutingWeights:
    capability_match: float = 10.0
    historical_quality: float = 4.0
    availability: float = 5.0
    structured_output_bonus: float = 1.5
    priority_weight: float = 1.0
    cost_penalty: float = 0.5
    failure_penalty: float = 8.0
    risk_review_bonus: float = 3.0
    learned_rule_weight: float = 2.0
    exploration_weight: float = 0.6


@dataclass(frozen=True)
class _Candidate:
    agent: Agent
    model: ModelInfo
    score: float
    reason: str


def _stable_jitter(*parts: str) -> float:
    """A deterministic pseudo-random value in [-0.5, 0.5] -- exploration
    without flaky, non-reproducible test behavior."""
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return (int.from_bytes(digest[:4], "big") / 0xFFFFFFFF) - 0.5


class Router:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        model_registry: ModelRegistry,
        provider_pool: ProviderPool,
        health_monitor: ProviderHealthMonitor,
        weights: RoutingWeights | None = None,
        *,
        performance_tracker: ModelPerformanceTracker | None = None,
        rule_resolver: RuleResolver | None = None,
    ) -> None:
        self._agents = agent_registry
        self._models = model_registry
        self._pool = provider_pool
        self._health = health_monitor
        self._weights = weights or RoutingWeights()
        self._performance = performance_tracker
        self._rules = rule_resolver

    async def route(
        self,
        step: PlanStep,
        *,
        risk: RiskLevel = RiskLevel.LOW,
        project_id: str | None = None,
        exclude_agent_ids: frozenset[str] = frozenset(),
    ) -> RoutingDecision:
        category = step.input.get("category") if isinstance(step.input, dict) else None
        rule_adjustments: dict[str, tuple[float, str]] = {}
        if self._rules is not None:
            adjustments = await self._rules.routing_adjustments(category=category, project_id=project_id)
            for adj in adjustments:
                rule_adjustments[adj.agent_id] = (adj.delta, adj.reason)

        candidates = await self._build_candidates(
            step, risk=risk, exclude_agent_ids=exclude_agent_ids, category=category,
            rule_adjustments=rule_adjustments,
        )
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

    async def _build_candidates(
        self,
        step: PlanStep,
        *,
        risk: RiskLevel,
        exclude_agent_ids: frozenset[str],
        category: str | None,
        rule_adjustments: dict[str, tuple[float, str]],
    ) -> list[_Candidate]:
        if step.assigned_agent_id:
            explicit = self._agents.get(step.assigned_agent_id)
            pool = [explicit] if explicit else []
            return await self._score_pool(
                pool, step, risk=risk, exclude_agent_ids=exclude_agent_ids, category=category,
                rule_adjustments=rule_adjustments,
            )

        pool = self._agents.find_by_capability(step.required_capability)
        candidates = await self._score_pool(
            pool, step, risk=risk, exclude_agent_ids=exclude_agent_ids, category=category,
            rule_adjustments=rule_adjustments,
        )
        if candidates:
            return candidates

        # No usable candidate matched the capability directly (either none
        # exist, or every match was excluded/unregistered/model-less) --
        # only *then* fall back to the generalist, so a fallback/retry that
        # excludes the primary agent still has somewhere to go.
        fallback = self._agents.get(_FALLBACK_AGENT_ID)
        return await self._score_pool(
            [fallback] if fallback else [], step, risk=risk, exclude_agent_ids=exclude_agent_ids,
            category=category, rule_adjustments=rule_adjustments,
        )

    async def _score_pool(
        self,
        pool: Iterable[Agent | None],
        step: PlanStep,
        *,
        risk: RiskLevel,
        exclude_agent_ids: frozenset[str],
        category: str | None,
        rule_adjustments: dict[str, tuple[float, str]],
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
            score, reason = await self._score(
                agent, model, step, risk=risk, category=category,
                rule_adjustment=rule_adjustments.get(agent.id),
            )
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

    async def _score(
        self,
        agent: Agent,
        model: ModelInfo,
        step: PlanStep,
        *,
        risk: RiskLevel,
        category: str | None,
        rule_adjustment: tuple[float, str] | None,
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

        observations = 0
        if self._performance is not None:
            rate, observations = await self._performance.get_verified_success_rate(
                provider=agent.provider, model=model.model_id, agent_id=agent.id,
                task_category=category or "general", risk=risk.value,
            )
            shrinkage = min(1.0, observations / _MIN_OBSERVATIONS_FOR_FULL_WEIGHT)
            historical_term = w.historical_quality * shrinkage * (rate - 0.5) * 2
            score += historical_term
            if observations > 0 and abs(historical_term) > 0.5:
                reasons.append(
                    f"histórico de {observations} execuções ({rate:.0%} de sucesso verificado)"
                )

            if risk == RiskLevel.LOW:
                jitter = w.exploration_weight * _stable_jitter(step.id, agent.id, model.model_id)
                jitter /= 1.0 + observations
                score += jitter

        if rule_adjustment is not None:
            delta, rule_reason = rule_adjustment
            score += w.learned_rule_weight * delta
            reasons.append(rule_reason)

        reason_text = ", ".join(reasons) if reasons else "melhor opção disponível para a etapa"
        return score, f"{agent.name} selecionado porque {reason_text}."
