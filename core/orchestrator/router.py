"""Router.

Decides which agent (and, transitively, which provider) executes each plan
step. Stage 1 routes purely by declared capability against the mocked
`AgentRegistry`, falling back to a general-purpose agent when no specialist
matches -- the same interface a cost/latency/quality-aware router will
implement in a later stage.
"""

from __future__ import annotations

from core.agents.models import Agent
from core.agents.registry import AgentRegistry
from core.orchestrator.models import PlanStep, RoutingDecision
from core.utils.errors import NotFoundError

_FALLBACK_AGENT_ID = "agent_generalist"


class Router:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def route(self, step: PlanStep) -> RoutingDecision:
        candidates = self._registry.find_by_capability(step.required_capability)
        agent: Agent | None
        if candidates:
            agent = candidates[0]
            reason = f"Matched capability '{step.required_capability}'."
        else:
            agent = self._registry.get(_FALLBACK_AGENT_ID)
            reason = f"No specialist for '{step.required_capability}'; used fallback generalist."

        if agent is None:
            raise NotFoundError("No agent available to route to (registry is empty).")

        return RoutingDecision(
            step_id=step.id, agent_id=agent.id, provider=agent.provider, reason=reason
        )
