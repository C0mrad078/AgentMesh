"""The bridge server loop: reads one JSON-line request at a time from the
parent Tauri process, dispatches it, and writes back exactly one JSON-line
response, while independently streaming `event` lines pushed by the
orchestration engine (execution progress) as they occur.

Session validation: every `request` must carry the `session` token that was
handed to this sidecar process via the `ORCH_SESSION_TOKEN` environment
variable at spawn time (see `core.bridge.main`). A request with a missing or
mismatched token is rejected with `UNAUTHORIZED` and never reaches a
handler -- this is what stands in for the process-identity guarantee that a
plain stdio pipe already gives us, made explicit and testable.
"""

from __future__ import annotations

import asyncio
import json

from core.bridge.context import BridgeContext
from core.bridge.errors import to_error_payload
from core.bridge.handlers import dispatch
from core.bridge.protocol import (
    EventMessage,
    HelloMessage,
    ResponseMessage,
)
from core.bridge.transport import StdioTransport
from core.orchestrator.event_bus import OrchestrationEvent
from core.orchestrator.events import ExecutionEvent
from core.providers.base import ProviderHealthStatus
from core.providers.health import ProviderHealthSnapshot
from core.utils.errors import UnauthorizedError
from core.utils.logging import get_logger, log_event

logger = get_logger("bridge.server")

_REQUEST_TIMEOUT_SECONDS = 30.0
_MEDIUM_REQUEST_TIMEOUT_SECONDS = 60.0
_RESTORE_REQUEST_TIMEOUT_SECONDS = 120.0
# Delivery gates and bounded worker/reviewer cycles can outlive an interactive
# request. Each subprocess still has its own timeout; cancellation keeps a
# durable recovery intent instead of blindly replaying remote mutations.
_DELIVERY_REQUEST_TIMEOUT_SECONDS = 10800.0
_LONG_DELIVERY_COMMANDS = frozenset({
    "delivery.preflight.run", "delivery.ci.assign_fix", "delivery.remote.push",
    "delivery.pr.create", "delivery.pr.update", "delivery.merge.execute",
    "delivery.rollback.execute",
})
_LONG_DEPLOYMENT_COMMANDS = frozenset({
    "deployment.predeploy.run", "deployment.run.execute",
    "deployment.promote.execute", "deployment.rollback.execute",
})
_MEDIUM_TIMEOUT_COMMANDS = frozenset({
    "system.diagnostics.export",
    "system.backup.create",
})
_RESTORE_TIMEOUT_COMMANDS = frozenset({
    "system.backup.restore",
})


def request_timeout_seconds(command: str) -> float:
    if command in _RESTORE_TIMEOUT_COMMANDS:
        return _RESTORE_REQUEST_TIMEOUT_SECONDS
    if command in _MEDIUM_TIMEOUT_COMMANDS:
        return _MEDIUM_REQUEST_TIMEOUT_SECONDS
    if command in _LONG_DELIVERY_COMMANDS or command in _LONG_DEPLOYMENT_COMMANDS:
        return _DELIVERY_REQUEST_TIMEOUT_SECONDS
    return _REQUEST_TIMEOUT_SECONDS



def make_event_sink(transport: StdioTransport):
    """Build an `EventSink` that streams execution progress to the parent
    process as `event` lines. Standalone (not a `BridgeServer` method) so it
    can be constructed before the `BridgeContext` it will be wired into.
    """

    async def sink(event: ExecutionEvent) -> None:
        message = EventMessage(
            event="execution.progress",
            payload={
                "execution_id": event.execution_id,
                "task_id": event.task_id,
                "phase": event.phase.value,
                "phase_label": event.phase_label,
                "status": event.status.value,
                "detail": event.detail,
            },
        )
        await transport.write_line(message.model_dump_json())

    return sink


def make_orchestration_event_sink(transport: StdioTransport):
    """Forwards every fine-grained `OrchestrationEvent` (agent selected,
    provider call started/completed, tool call, retry, verification, ...)
    to the frontend as its own bridge event, named after the event type
    (e.g. `agent.selected`). This is what backs the optional "Execution
    Inspector" / debug view; the step-by-step progress board only needs
    `execution.progress` (see `make_event_sink` above).
    """

    async def sink(event: OrchestrationEvent) -> None:
        message = EventMessage(
            event=event.type.value,
            payload={
                "execution_id": event.execution_id,
                "task_id": event.task_id,
                **event.payload,
            },
        )
        await transport.write_line(message.model_dump_json())

    return sink


_UNHEALTHY_STATUSES = frozenset({
    ProviderHealthStatus.RATE_LIMITED, ProviderHealthStatus.DEGRADED, ProviderHealthStatus.UNAVAILABLE,
})


def make_provider_health_bridge_sink(transport: StdioTransport):
    """Stage 3, spec section 20/31/41: the real gap this stage exists to
    close -- until now, `ProviderHealthMonitor.on_change` only fed the
    `provider_health` DB table (`make_provider_health_sink`); the Virtual
    Office had no way to learn a provider went into cooldown except a 15s
    poll. This mirrors `ProviderHealthMonitor.on_change`'s own
    `(provider, snapshot)` shape and pushes exactly two real, named events:
    `provider.rate_limited` (any unhealthy status, carrying `retryAfter`
    seconds when the adapter reported one -- never fabricated) and
    `provider.recovered` (transition back to healthy). Everything else
    (DEGRADED vs. RATE_LIMITED vs. UNAVAILABLE nuance, exact error text) is
    still in the payload for the UI to read, but the *office* only ever
    needs "should this agent's body still be at its desk or not".
    """
    previously_unhealthy: set[str] = set()

    async def sink(provider: str, snapshot: ProviderHealthSnapshot) -> None:
        is_unhealthy = snapshot.status in _UNHEALTHY_STATUSES
        was_unhealthy = provider in previously_unhealthy

        if is_unhealthy and not was_unhealthy:
            previously_unhealthy.add(provider)
            message = EventMessage(
                event="provider.rate_limited",
                payload={
                    "providerId": provider,
                    "status": snapshot.status.value,
                    "retryAfter": snapshot.retry_after_seconds,
                    "lastError": snapshot.last_error,
                },
            )
            await transport.write_line(message.model_dump_json())
        elif was_unhealthy and not is_unhealthy:
            previously_unhealthy.discard(provider)
            message = EventMessage(event="provider.recovered", payload={"providerId": provider})
            await transport.write_line(message.model_dump_json())
        # A status change between two unhealthy states (e.g. DEGRADED ->
        # RATE_LIMITED) or two healthy ones is real but not a *transition*
        # the office needs to act on again -- the agent is already
        # resting/sleeping, or already working; no new event is emitted.

    return sink


class BridgeServer:
    def __init__(self, transport: StdioTransport, session_token: str, context: BridgeContext) -> None:
        self._transport = transport
        self._session_token = session_token
        self._context = context

    async def send_hello(self) -> None:
        import os

        hello = HelloMessage(session=self._session_token, pid=os.getpid())
        await self._transport.write_line(hello.model_dump_json())

    async def serve_forever(self) -> None:
        await self.send_hello()
        while True:
            line = await self._transport.read_line()
            if line is None:
                logger.info("stdin_closed_exiting")
                return
            if not line.strip():
                continue
            asyncio.create_task(self._handle_line(line))

    async def _handle_line(self, line: str) -> None:
        request_id = None
        request_timeout = _REQUEST_TIMEOUT_SECONDS
        try:
            raw = json.loads(line)
            request_id = raw.get("id")
            if raw.get("type") != "request":
                raise UnauthorizedError("Only 'request' messages are accepted from the client.")
            if raw.get("session") != self._session_token:
                raise UnauthorizedError("Invalid or missing session token.")

            command = raw.get("command")
            params = raw.get("params", {})
            if request_id is None or not isinstance(request_id, str):
                raise UnauthorizedError("Request is missing a valid 'id'.")

            log_event(logger, 10, "request_received", context={"command": command, "id": request_id})

            request_timeout = request_timeout_seconds(command)
            result = await asyncio.wait_for(
                dispatch(command, params, self._context), timeout=request_timeout
            )
            response = ResponseMessage(id=request_id, ok=True, result=result)

        except TimeoutError:
            response = ResponseMessage(
                id=request_id or "unknown", ok=False,
                error=to_error_payload_from_timeout(request_timeout),
            )
        except Exception as exc:  # noqa: BLE001 - top-level per-request containment
            response = ResponseMessage(id=request_id or "unknown", ok=False, error=to_error_payload(exc))

        await self._transport.write_line(response.model_dump_json())


def to_error_payload_from_timeout(timeout_seconds: float | None = None):
    from core.bridge.protocol import ErrorPayload
    from core.utils.errors import ErrorCode

    return ErrorPayload(
        code=ErrorCode.TIMEOUT.value,
        message=f"Request exceeded the {timeout_seconds if timeout_seconds is not None else _REQUEST_TIMEOUT_SECONDS}s server-side timeout.",
        details={},
    )
