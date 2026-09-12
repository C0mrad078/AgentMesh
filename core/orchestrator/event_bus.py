"""Internal event bus.

Every meaningful thing the orchestrator does during an execution -- an
agent being selected, a provider call starting/finishing, a tool running, a
verification failing, a retry kicking in -- is published here as one
`OrchestrationEvent`. Subscribers fan it out to:

  * the bridge, so the frontend can render a live event/debug view;
  * `execution_events` in SQLite, for the history/debug view and as the
    data Stage 3's Reflection Engine will mine;
  * the audit log, for the security-relevant subset.

Event payloads carry only objective, structured data (agent/provider/model
ids, durations, token counts, cost, a short human-readable reason, error
codes) -- never a model's private reasoning/chain-of-thought, and never a
secret. See the module docstring in `core.security.secret_scanner` for the
redaction pass applied before anything derived from file/tool content is
attached to an event.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.utils.logging import get_logger
from core.utils.time import utc_now_iso

logger = get_logger("orchestrator.event_bus")


class EventType(str, Enum):
    EXECUTION_CREATED = "execution.created"
    PLAN_CREATED = "plan.created"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    AGENT_SELECTED = "agent.selected"
    PROVIDER_REQUEST_STARTED = "provider.request.started"
    PROVIDER_REQUEST_COMPLETED = "provider.request.completed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_FAILED = "verification.failed"
    RETRY_STARTED = "retry.started"
    FALLBACK_USED = "fallback.used"
    CIRCUIT_OPENED = "circuit.opened"
    BUDGET_WARNING = "budget.warning"
    BUDGET_EXCEEDED = "budget.exceeded"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_CANCELLED = "execution.cancelled"
    REFLECTION_STARTED = "reflection.started"
    REFLECTION_COMPLETED = "reflection.completed"
    LEARNING_UPDATED = "learning.updated"


@dataclass(frozen=True)
class OrchestrationEvent:
    type: EventType
    execution_id: str
    task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)


EventSubscriber = Callable[[OrchestrationEvent], "Awaitable[None] | None"]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[EventSubscriber] = []

    def subscribe(self, callback: EventSubscriber) -> None:
        self._subscribers.append(callback)

    async def publish(self, event: OrchestrationEvent) -> None:
        for callback in self._subscribers:
            try:
                result = callback(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.error(
                    "event_subscriber_failed",
                    extra={"context": {"event_type": event.type.value}},
                )
