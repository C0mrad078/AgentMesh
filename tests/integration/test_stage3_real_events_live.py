"""Genuinely live, Stage 3 specific: proves the *exact* real events the
Virtual Office's `RealOfficeAdapter` consumes actually fire, with real
data, when a real task runs through the real, installed, authenticated
Codex CLI -- not `MockProvider`. This is the backend half of "eventos
reais chegam ao frontend" (spec section 101's gate); the bridge push
mechanism itself (Python -> Rust -> Tauri -> `orchestrator://event`) was
already real and working before this stage (see VIRTUAL_OFFICE.md) and is
covered by `tests/python/test_bridge.py`'s server-level tests -- this
file proves the *content* published to it is real.

Skipped unless `RUN_LIVE_AI_TESTS=true` AND `codex` is installed and
authenticated. Never required, never run in CI by default.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.orchestrator.event_bus import EventType, OrchestrationEvent
from core.orchestrator.models import ExecutionStatus
from core.projects.models import ProjectCreate
from core.providers.base import ProviderConnectionState
from core.providers.codex_cli_provider import CodexCliProvider
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskMode, TaskStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AI_TESTS") != "true" or shutil.which("codex") is None,
    reason="Live Stage 3 event test: set RUN_LIVE_AI_TESTS=true with `codex` installed to run.",
)


async def test_a_real_codex_cli_task_publishes_the_real_events_the_office_translates(
    tmp_path: Path,
) -> None:
    status = await CodexCliProvider().get_status()
    if status.state != ProviderConnectionState.CONNECTED:
        pytest.skip(f"codex CLI is installed but not authenticated ({status.detail!r}).")

    ctx = await build_context(
        tmp_path / "stage3_live.db", secret_store=InMemorySecretStore(), detect_cli_providers=True,
    )
    try:
        events: list[OrchestrationEvent] = []
        ctx.event_bus.subscribe(lambda e: events.append(e))

        project = await ctx.project_service.create_project(ProjectCreate(name="Stage 3 Live Event Test"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id,
                title="Reply with exactly the text PROBE_OK, using no tools.",
                mode=TaskMode.MANUAL,
                input={"agent_id": "agent_codex_cli_developer", "risk": "low"},
            )
        )

        execution = await ctx.engine.run(task)

        assert execution.status == ExecutionStatus.COMPLETED
        final_task = await ctx.task_service.get_task(task.id)
        assert final_task.status == TaskStatus.COMPLETED

        # 1) A real agent.selected naming the exact real agent/provider --
        # this is what `RealOfficeAdapter` maps to the "Codex" visual role.
        selected = [e for e in events if e.type == EventType.AGENT_SELECTED]
        assert selected, "no agent.selected event was published"
        assert any(
            e.payload.get("agent_id") == "agent_codex_cli_developer"
            and e.payload.get("provider") == "codex_cli"
            for e in selected
        )

        # 2) A real step.started/step.completed pair for that same agent,
        # with real, non-fabricated token/cost data -- exactly what feeds
        # the "no fake progress" rule (spec section 28/70): this office
        # never shows a percentage, only phase-based real state, and this
        # is the real data backing that choice.
        started = [e for e in events if e.type == EventType.STEP_STARTED]
        completed = [e for e in events if e.type == EventType.STEP_COMPLETED and "agent_id" in e.payload]
        assert started and completed
        work_completion = next(e for e in completed if e.payload.get("agent_id") == "agent_codex_cli_developer")
        assert work_completion.payload["provider"] == "codex_cli"
        assert work_completion.payload["success"] is True
        assert isinstance(work_completion.payload.get("input_tokens"), int)
        assert work_completion.payload["input_tokens"] > 0

        # 3) The execution itself completing, real and terminal.
        assert any(e.type == EventType.EXECUTION_COMPLETED for e in events)

        # 4) No secret ever rode along in a payload (spec section 89/90).
        import json
        serialized = json.dumps([e.payload for e in events])
        assert "sk-" not in serialized  # a leaked API-key-shaped string would show up in a stray payload
    finally:
        await ctx.close()
