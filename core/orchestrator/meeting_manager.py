"""Real multi-agent collaborative-planning detection (AgentMash Stage 3,
spec section 15-19).

There is no separate "should we meet" reasoning engine here -- that would
be a much deeper change to the Planner than this stage's scope. What IS
real: a DAG execution layer with 2+ steps under `TaskMode.DEBATE` or
`TaskMode.CONSENSUS` *is* multiple agents genuinely working the same
problem concurrently (the Planner already only produces such a layer for
those two modes -- see `core.orchestrator.planner`), which is exactly the
condition Stage 1/2's now-dormant frontend logic
(`office/stateMachine.ts::deriveOfficeSnapshot`) used to derive a virtual
"meeting" from. This module makes that same real signal a first-class,
named backend event instead of something only inferred client-side, and
is the one and only thing that decides "these agent ids are meeting" --
`ExecutionEngine` never publishes `MEETING_*` on its own (spec section
59: never hardcode which/how many agents meet).
"""

from __future__ import annotations

from core.orchestrator.event_bus import EventBus, EventType, OrchestrationEvent
from core.orchestrator.models import PlanStep, RoutingDecision
from core.tasks.models import TaskMode

_MEETING_MODES = frozenset({TaskMode.DEBATE, TaskMode.CONSENSUS})


class MeetingManager:
    def __init__(self, event_bus: EventBus) -> None:
        self._events = event_bus

    def participants_for(self, mode: TaskMode, layer: list[PlanStep], routes: dict[str, RoutingDecision]) -> list[str]:
        """Real, dynamic participant list (spec section 58/59) -- never a
        fixed roster. Empty when this layer isn't a real meeting."""
        if mode not in _MEETING_MODES or len(layer) < 2:
            return []
        agent_ids = [routes[step.id].agent_id for step in layer if step.id in routes]
        # Dedupe while preserving order -- two steps in the same layer
        # could in principle route to the same agent.
        seen: set[str] = set()
        unique = []
        for agent_id in agent_ids:
            if agent_id not in seen:
                seen.add(agent_id)
                unique.append(agent_id)
        return unique if len(unique) >= 2 else []

    async def meeting_created(self, execution_id: str, task_id: str, participants: list[str]) -> None:
        await self._events.publish(OrchestrationEvent(
            type=EventType.MEETING_CREATED, execution_id=execution_id, task_id=task_id,
            payload={"participants": participants},
        ))

    async def meeting_started(self, execution_id: str, task_id: str, participants: list[str]) -> None:
        await self._events.publish(OrchestrationEvent(
            type=EventType.MEETING_STARTED, execution_id=execution_id, task_id=task_id,
            payload={"participants": participants},
        ))

    async def meeting_completed(self, execution_id: str, task_id: str, participants: list[str]) -> None:
        await self._events.publish(OrchestrationEvent(
            type=EventType.MEETING_COMPLETED, execution_id=execution_id, task_id=task_id,
            payload={"participants": participants},
        ))
