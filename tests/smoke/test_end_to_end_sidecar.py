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
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_TOKEN = "smoke-test-session-token"
REQUEST_TIMEOUT_SECONDS = 10.0


class SidecarClient:
    """Minimal JSON-lines client mirroring the Rust `BridgeManager`."""

    def __init__(self, data_dir: Path) -> None:
        env = dict(os.environ)
        env["ORCH_SESSION_TOKEN"] = SESSION_TOKEN
        env["ORCH_DATA_DIR"] = str(data_dir)
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
        self.hello = self._read_message(timeout=REQUEST_TIMEOUT_SECONDS)
        assert self.hello["type"] == "hello", f"expected hello, got {self.hello}"
        assert self.hello["session"] == SESSION_TOKEN

    def _read_message(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if line:
                return json.loads(line)
        raise TimeoutError("Timed out waiting for a message from the sidecar.")

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
    client = SidecarClient(data_dir)
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
    reopened = SidecarClient(data_dir)
    try:
        got = reopened.call("task.get", {"task_id": task["id"]})
        assert got["ok"] is True
        assert got["result"]["status"] == "completed"
        assert got["result"]["result"] is not None

        projects_after_reopen = reopened.call("project.list")
        assert any(p["id"] == project["id"] for p in projects_after_reopen["result"])
    finally:
        reopened.close()


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
