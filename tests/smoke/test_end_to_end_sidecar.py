"""End-to-end smoke test for the full Orquestrador flow, driven against the
*real* sidecar process (not an in-process `BridgeContext`) speaking the
actual newline-JSON protocol over real stdin/stdout pipes -- exactly what
the Tauri shell does in `desktop/src-tauri/src/bridge/manager.rs`.

This is the automated stand-in for the manual smoke-test flow described in
the project brief:

    Abrir aplicativo -> Criar projeto -> Abrir projeto -> Enviar tarefa ->
    Criar execucao -> Acompanhar etapas -> MockProvider responder ->
    Verifier validar -> Resultado aparecer -> Persistir ->
    Fechar/reabrir historico -> Resultado continuar disponivel

Driving the actual native Tauri window is out of scope for an automated
test in this environment (there is no GUI automation harness for a native
webview here), so this test proves the same thing from the boundary Tauri
itself talks to: a real Python process, spawned the same way, over the same
protocol, with a real SQLite database on disk that is closed and reopened
mid-test to prove persistence.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_TOKEN = "smoke-test-session-token"
REQUEST_TIMEOUT_SECONDS = 10.0


class SidecarClient:
    """Minimal JSON-lines client mirroring the Rust `BridgeManager`."""

    def __init__(self, data_dir: Path, *, enable_mock_provider: bool = False) -> None:
        env = dict(os.environ)
        env["ORCH_SESSION_TOKEN"] = SESSION_TOKEN
        env["ORCH_DATA_DIR"] = str(data_dir)
        if enable_mock_provider:
            env["ORCH_ENABLE_MOCK_PROVIDER"] = "1"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "core.bridge.main"],
            cwd=str(REPO_ROOT),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        # `Popen.stdout.readline()` is a blocking OS-pipe read with no
        # timeout of its own -- a `while monotonic() < deadline: readline()`
        # loop does NOT enforce the deadline, since the deadline is only
        # checked between calls, never during one; a sidecar that never
        # writes a line hangs this client forever. A background thread
        # feeding a `Queue` lets `_read_message` use `Queue.get(timeout=...)`,
        # which is a real, interruptible wall-clock timeout, and works
        # identically on Windows (unlike `select()` on a pipe).
        self._lines: queue.Queue[str] = queue.Queue()
        self._reader_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader_thread.start()
        self.hello = self._read_message(timeout=REQUEST_TIMEOUT_SECONDS)
        assert self.hello["type"] == "hello", f"expected hello, got {self.hello}"
        assert self.hello["session"] == SESSION_TOKEN

    def _pump_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line)

    def _read_message(self, timeout: float) -> dict:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("Timed out waiting for a message from the sidecar.") from None
        return json.loads(line)

    def call(self, command: str, params: dict | None = None) -> dict:
        request = {
            "type": "request",
            "id": uuid.uuid4().hex,
            "session": SESSION_TOKEN,
            "command": command,
            "params": params or {},
        }
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()

        while True:
            message = self._read_message(timeout=REQUEST_TIMEOUT_SECONDS)
            if message.get("type") == "response" and message.get("id") == request["id"]:
                return message
            # Ignore interleaved `event` messages (execution progress).

    def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "orchestrator-smoke-data"


def test_full_smoke_flow_through_the_real_sidecar_process(data_dir: Path) -> None:
    """Exercises the full autonomous pipeline with `ORCH_ENABLE_MOCK_PROVIDER=1`
    (see `core.bridge.main`) -- a deterministic, test-only opt-in that
    registers `MockProvider` so this can run without real API keys. The
    default, key-less behavior is covered separately by
    `test_no_provider_configured_reports_a_clear_offline_message` below.
    """
    client = SidecarClient(data_dir, enable_mock_provider=True)
    try:
        # health.check
        health = client.call("health.check")
        assert health["ok"] is True
        assert health["result"]["status"] == "ok"

        # Criar projeto
        create_project = client.call("project.create", {"name": "Smoke Test Project"})
        assert create_project["ok"] is True
        project = create_project["result"]
        assert project["name"] == "Smoke Test Project"

        # Abrir projeto (list + get)
        listed = client.call("project.list")
        assert any(p["id"] == project["id"] for p in listed["result"])
        fetched = client.call("project.get", {"project_id": project["id"]})
        assert fetched["result"]["id"] == project["id"]

        # Enviar tarefa
        create_task = client.call(
            "task.create",
            {
                "project_id": project["id"],
                "title": "Resuma o objetivo do produto",
                "input": {"scenario": "success"},
            },
        )
        assert create_task["ok"] is True
        task = create_task["result"]
        assert task["status"] == "queued"

        # Criar execucao (dispara o pipeline completo de forma assincrona)
        start = client.call("execution.start", {"task_id": task["id"]})
        assert start["ok"] is True

        # Acompanhar etapas / aguardar MockProvider responder e Verifier validar
        final_task = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            got = client.call("task.get", {"task_id": task["id"]})
            assert got["ok"] is True
            if got["result"]["status"] in ("completed", "failed", "cancelled"):
                final_task = got["result"]
                break
            time.sleep(0.1)

        assert final_task is not None, "Task never reached a terminal state."
        assert final_task["status"] == "completed"
        assert final_task["result"] is not None

        # Resultado aparecer: confirmar execucao + etapas persistidos
        executions = client.call("execution.list", {"project_id": project["id"]})
        assert len(executions["result"]) == 1
        execution = executions["result"][0]
        assert execution["status"] == "completed"

        steps = client.call("execution.steps.list", {"execution_id": execution["id"]})
        phase_steps = [s for s in steps["result"] if s["kind"] == "phase"]
        assert len(phase_steps) == 6
        assert all(s["status"] == "completed" for s in phase_steps)

    finally:
        client.close()

    # Fechar/reabrir historico: um processo totalmente novo, mesma pasta de
    # dados, deve continuar enxergando o mesmo resultado.
    reopened = SidecarClient(data_dir, enable_mock_provider=True)
    try:
        got = reopened.call("task.get", {"task_id": task["id"]})
        assert got["ok"] is True
        assert got["result"]["status"] == "completed"
        assert got["result"]["result"] is not None

        projects_after_reopen = reopened.call("project.list")
        assert any(p["id"] == project["id"] for p in projects_after_reopen["result"])
    finally:
        reopened.close()


def test_no_provider_configured_reports_a_clear_offline_message(data_dir: Path) -> None:
    """Offline Mode: with no API key configured (the default -- this client
    does *not* set `ORCH_ENABLE_MOCK_PROVIDER`), the app must still open,
    create/list projects, and create tasks. Only actually *starting* an
    execution should fail, and it must fail with a clear, actionable
    message rather than a generic error or a crash.
    """
    client = SidecarClient(data_dir)
    try:
        project = client.call("project.create", {"name": "Offline Project"})["result"]
        task = client.call(
            "task.create", {"project_id": project["id"], "title": "Do something"}
        )["result"]

        start = client.call("execution.start", {"task_id": task["id"]})
        assert start["ok"] is True  # fire-and-forget accepted; failure surfaces on the task

        final_task = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            got = client.call("task.get", {"task_id": task["id"]})
            if got["result"]["status"] in ("completed", "failed", "partial", "cancelled"):
                final_task = got["result"]
                break
            time.sleep(0.1)

        assert final_task is not None
        assert final_task["status"] == "failed"
        assert "provider" in final_task["result"]["error"].lower()

        # The app itself, and every non-AI feature, must still work fine.
        health = client.call("health.check")
        assert health["ok"] is True
        projects = client.call("project.list")
        assert any(p["id"] == project["id"] for p in projects["result"])
    finally:
        client.close()


def test_invalid_request_and_unknown_command_do_not_crash_the_sidecar(data_dir: Path) -> None:
    client = SidecarClient(data_dir)
    try:
        response = client.call("project.get", {})
        assert response["ok"] is False
        assert response["error"]["code"] == "VALIDATION_ERROR"

        response = client.call("this.command.does.not.exist")
        assert response["ok"] is False
        assert response["error"]["code"] == "UNKNOWN_COMMAND"

        # The sidecar must still be alive and answering after both errors.
        health = client.call("health.check")
        assert health["ok"] is True
    finally:
        client.close()


def test_wrong_session_token_is_rejected(data_dir: Path) -> None:
    client = SidecarClient(data_dir)
    try:
        request = {
            "type": "request",
            "id": uuid.uuid4().hex,
            "session": "wrong-token",
            "command": "health.check",
            "params": {},
        }
        assert client.process.stdin is not None
        client.process.stdin.write(json.dumps(request) + "\n")
        client.process.stdin.flush()
        response = client._read_message(timeout=REQUEST_TIMEOUT_SECONDS)
        assert response["ok"] is False
        assert response["error"]["code"] == "UNAUTHORIZED"
    finally:
        client.close()


def test_read_message_enforces_a_real_timeout_when_the_sidecar_writes_nothing() -> None:
    # Regression test: `_read_message` used to loop on the blocking
    # `Popen.stdout.readline()` with a deadline that was only checked
    # *between* calls, so a sidecar that never writes a line hung the
    # client forever instead of raising after `timeout` seconds. The
    # queue-fed background reader must enforce a real, bounded timeout.
    client = object.__new__(SidecarClient)
    client._lines = queue.Queue()  # never fed -- simulates a silent sidecar

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        client._read_message(timeout=0.3)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"_read_message blocked for {elapsed:.2f}s instead of honoring its timeout"
