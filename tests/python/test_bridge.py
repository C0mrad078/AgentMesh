from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.bridge.protocol import RequestMessage, parse_incoming
from core.bridge.server import BridgeServer
from core.security.secret_store import InMemorySecretStore
from core.utils.errors import UnknownCommandError, ValidationError

SESSION = "test-session-token"


class FakeTransport:
    def __init__(self, incoming_lines: list[str]) -> None:
        self._incoming = list(incoming_lines)
        self.written: list[str] = []

    async def read_line(self) -> str | None:
        if not self._incoming:
            return None
        return self._incoming.pop(0)

    async def write_line(self, data: str) -> None:
        self.written.append(data)


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "bridge-test.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.db.close()


def test_parse_incoming_valid_request() -> None:
    raw = {"type": "request", "id": "abc", "session": SESSION, "command": "health.check", "params": {}}
    parsed = parse_incoming(raw)
    assert isinstance(parsed, RequestMessage)
    assert parsed.command == "health.check"


def test_parse_incoming_rejects_wrong_type() -> None:
    with pytest.raises(ValueError):
        parse_incoming({"type": "response", "id": "x"})


async def test_dispatch_unknown_command_rejected(ctx) -> None:
    with pytest.raises(UnknownCommandError):
        await dispatch("does.not.exist", {}, ctx)


async def test_dispatch_health_check(ctx) -> None:
    result = await dispatch("health.check", {}, ctx)
    assert result == {"status": "ok"}


async def test_dispatch_project_create_and_get_roundtrip(ctx) -> None:
    created = await dispatch("project.create", {"name": "Bridge Project"}, ctx)
    assert created["name"] == "Bridge Project"
    fetched = await dispatch("project.get", {"project_id": created["id"]}, ctx)
    assert fetched["id"] == created["id"]


async def test_dispatch_validates_params(ctx) -> None:
    with pytest.raises(ValidationError):
        await dispatch("project.get", {}, ctx)


async def test_dispatch_execution_cancel_reports_whether_it_was_tracked(ctx) -> None:
    result = await dispatch("execution.cancel", {"execution_id": "exec_unknown"}, ctx)
    assert result == {"execution_id": "exec_unknown", "cancel_requested": False}


async def test_dispatch_execution_start_rejects_a_non_queued_task(ctx) -> None:
    project = await dispatch("project.create", {"name": "Start Guard"}, ctx)
    task = await dispatch(
        "task.create", {"project_id": project["id"], "title": "Only once"}, ctx
    )
    await dispatch("execution.start", {"task_id": task["id"]}, ctx)

    # Give the fire-and-forget engine run a chance to move the task off
    # 'queued' before asserting the guard rejects a second start.
    await asyncio.sleep(0.05)

    with pytest.raises(ValidationError):
        await dispatch("execution.start", {"task_id": task["id"]}, ctx)


async def test_bridge_server_handles_valid_request(ctx) -> None:
    request = {
        "type": "request", "id": "r1", "session": SESSION, "command": "health.check", "params": {},
    }
    transport = FakeTransport([json.dumps(request)])
    server = BridgeServer(transport, SESSION, ctx)
    await server._handle_line(json.dumps(request))

    assert len(transport.written) == 1
    response = json.loads(transport.written[0])
    assert response["ok"] is True
    assert response["id"] == "r1"
    assert response["result"] == {"status": "ok"}


async def test_bridge_server_rejects_wrong_session_token(ctx) -> None:
    request = {
        "type": "request", "id": "r2", "session": "wrong-token", "command": "health.check", "params": {},
    }
    transport = FakeTransport([])
    server = BridgeServer(transport, SESSION, ctx)
    await server._handle_line(json.dumps(request))

    response = json.loads(transport.written[0])
    assert response["ok"] is False
    assert response["error"]["code"] == "UNAUTHORIZED"


async def test_bridge_server_handles_malformed_json_without_crashing(ctx) -> None:
    transport = FakeTransport([])
    server = BridgeServer(transport, SESSION, ctx)
    await server._handle_line("{not valid json")

    response = json.loads(transport.written[0])
    assert response["ok"] is False
    assert response["id"] == "unknown"


async def test_bridge_server_unknown_command_returns_structured_error(ctx) -> None:
    request = {
        "type": "request", "id": "r3", "session": SESSION, "command": "delete.everything", "params": {},
    }
    transport = FakeTransport([])
    server = BridgeServer(transport, SESSION, ctx)
    await server._handle_line(json.dumps(request))

    response = json.loads(transport.written[0])
    assert response["ok"] is False
    assert response["error"]["code"] == "UNKNOWN_COMMAND"


async def test_bridge_server_sends_hello_with_pid_and_session() -> None:
    transport = FakeTransport([])
    context = None
    server = BridgeServer(transport, SESSION, context)  # hello doesn't touch context
    await server.send_hello()
    hello = json.loads(transport.written[0])
    assert hello["type"] == "hello"
    assert hello["session"] == SESSION
    assert isinstance(hello["pid"], int)
