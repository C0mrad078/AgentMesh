"""EventBus subscribers that persist orchestration events.

Each factory here closes over one repository and reacts only to the event
types it cares about, so `core.bridge.context.build_context` can wire the
whole persistence story in a few `event_bus.subscribe(...)` calls without
`EventBus`/`ExecutionEngine` ever importing a repository directly.
"""

from __future__ import annotations

from core.database.repositories.execution_events_repo import ExecutionEventsRepository
from core.database.repositories.provider_health_repo import ProviderHealthRepository
from core.database.repositories.routing_decisions_repo import RoutingDecisionsRepository
from core.database.repositories.tool_calls_repo import ToolCallsRepository
from core.database.repositories.usage_metrics_repo import UsageMetricsRepository
from core.orchestrator.event_bus import EventType, OrchestrationEvent
from core.orchestrator.models import RoutingDecision
from core.providers.health import ProviderHealthSnapshot


def make_audit_trail_sink(repo: ExecutionEventsRepository):
    """Records every event verbatim -- the data source for the history
    page's "Execution Inspector" / debug view."""

    async def sink(event: OrchestrationEvent) -> None:
        if (
            event.type != EventType.MISSION_CHANGED
            and not event.type.value.startswith("delivery.")
            and not event.type.value.startswith("deployment:")
        ):
            await repo.record(event)

    return sink


def make_routing_decision_sink(repo: RoutingDecisionsRepository):
    async def sink(event: OrchestrationEvent) -> None:
        if event.type != EventType.AGENT_SELECTED:
            return
        payload = event.payload
        decision = RoutingDecision(
            step_id=payload["step_id"], agent_id=payload["agent_id"], provider=payload["provider"],
            model=payload["model"], reason=payload["reason"], score=payload.get("score", 0.0),
        )
        await repo.record(event.execution_id, decision)

    return sink


def make_tool_calls_sink(repo: ToolCallsRepository):
    async def sink(event: OrchestrationEvent) -> None:
        if event.type != EventType.TOOL_COMPLETED:
            return
        payload = event.payload
        await repo.record(
            execution_id=event.execution_id, step_id=payload.get("step_id"),
            agent_id=payload.get("agent_id"), tool_name=payload["tool"],
            arguments=payload.get("arguments", {}), error=payload.get("error"),
            duration_seconds=payload.get("duration_seconds"),
        )

    return sink


def make_provider_health_sink(repo: ProviderHealthRepository):
    """Matches `ProviderHealthMonitor.on_change`'s `(provider, snapshot)`
    callback shape, not the `EventBus` one -- health changes are not routed
    through `EventBus` since they are not tied to a single execution."""

    async def sink(provider: str, snapshot: ProviderHealthSnapshot) -> None:
        await repo.upsert(
            provider, snapshot.status.value,
            last_error=snapshot.last_error, consecutive_failures=snapshot.consecutive_failures,
        )

    return sink


def make_usage_metrics_sink(repo: UsageMetricsRepository):
    async def sink(event: OrchestrationEvent) -> None:
        if event.type != EventType.STEP_COMPLETED:
            return
        payload = event.payload
        if "input_tokens" not in payload:
            return  # synthesis steps don't carry usage
        await repo.record(
            execution_id=event.execution_id, step_id=payload.get("step_id"),
            agent_id=payload.get("agent_id"), provider=payload.get("provider") or "unknown",
            model=payload.get("model") or "unknown", input_tokens=payload.get("input_tokens", 0),
            output_tokens=payload.get("output_tokens", 0),
            estimated_cost_usd=payload.get("estimated_cost_usd", 0.0),
            duration_seconds=payload.get("duration_seconds", 0.0),
            success=bool(payload.get("success", False)), retries=max(payload.get("attempts", 1) - 1, 0),
        )

    return sink
