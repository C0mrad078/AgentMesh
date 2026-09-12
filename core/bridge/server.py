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
from core.utils.errors import UnauthorizedError
from core.utils.logging import get_logger, log_event

logger = get_logger("bridge.server")

_REQUEST_TIMEOUT_SECONDS = 30.0


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

            result = await asyncio.wait_for(
                dispatch(command, params, self._context), timeout=_REQUEST_TIMEOUT_SECONDS
            )
            response = ResponseMessage(id=request_id, ok=True, result=result)

        except TimeoutError:
            response = ResponseMessage(
                id=request_id or "unknown", ok=False,
                error=to_error_payload_from_timeout(),
            )
        except Exception as exc:  # noqa: BLE001 - top-level per-request containment
            response = ResponseMessage(id=request_id or "unknown", ok=False, error=to_error_payload(exc))

        await self._transport.write_line(response.model_dump_json())


def to_error_payload_from_timeout():
    from core.bridge.protocol import ErrorPayload
    from core.utils.errors import ErrorCode

    return ErrorPayload(
        code=ErrorCode.TIMEOUT.value,
        message=f"Request exceeded the {_REQUEST_TIMEOUT_SECONDS}s server-side timeout.",
        details={},
    )
