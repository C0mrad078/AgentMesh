"""Wire protocol for the Tauri <-> Python bridge.

## Transport decision

The bridge runs over the sidecar process's own **stdin/stdout**, framed as
newline-delimited JSON (one JSON object per line -- "JSON Lines"). This was
chosen over the alternatives for Tauri 2 sidecars:

  * **Named pipes / platform IPC** -- would require a POSIX implementation
    (Unix domain sockets) and a completely different Windows implementation
    (named pipes), doubling the surface area we'd have to get right and
    test on both platforms, for no behavioral benefit over stdio in a
    strict parent-owns-child sidecar relationship.
  * **localhost HTTP/TCP** -- requires picking and coordinating a port,
    handling bind failures/conflicts, and opens a loopback listener that
    (absent extra work) any other local process could probe or connect to.
    None of that is needed when the "client" is always the exact process
    that spawned the sidecar.

stdio is: already 1:1 process-scoped (no other process can read/write it
without OS-level debugging privileges), requires no port management, and is
the pattern Tauri's own sidecar/shell APIs are built around. A session
token exchanged at handshake (see `HelloMessage`) adds defense-in-depth on
top of that process-level isolation, and keeps this protocol forward
compatible with a future TCP transport if one is ever needed.

## Message shapes

  * `hello`    - sidecar -> parent, sent once at startup.
  * `request`  - parent -> sidecar, a command invocation.
  * `response` - sidecar -> parent, one per request, correlated by `id`.
  * `event`    - sidecar -> parent, unsolicited (e.g. execution progress).

Every message is validated against these Pydantic models before being
acted upon or written to the stream, so a malformed line can never reach
application code as untyped `dict` soup.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "1"


class HelloMessage(BaseModel):
    type: Literal["hello"] = "hello"
    version: str = PROTOCOL_VERSION
    session: str
    pid: int


class RequestMessage(BaseModel):
    type: Literal["request"] = "request"
    id: str
    session: str
    command: str
    params: dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ResponseMessage(BaseModel):
    type: Literal["response"] = "response"
    id: str
    ok: bool
    result: dict[str, Any] | list[Any] | None = None
    error: ErrorPayload | None = None


class EventMessage(BaseModel):
    type: Literal["event"] = "event"
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


def parse_incoming(raw: dict[str, Any]) -> RequestMessage:
    """Parse and validate a line received from the parent process.

    Only `request` messages are ever expected from the parent; anything
    else is a protocol violation and raises `ValueError` (the server layer
    turns that into a structured error response, not a crash).
    """
    msg_type = raw.get("type")
    if msg_type != "request":
        raise ValueError(f"Expected a 'request' message, got type={msg_type!r}")
    return RequestMessage.model_validate(raw)
