"""Same real proof as `test_stage3_real_events_live.py`, against the real,
installed, authenticated Claude Code CLI instead of Codex -- both of this
project's real CLI-backed agents are exercised through the actual engine
at least once, not just one of them.

Skipped unless `RUN_LIVE_AI_TESTS=true` AND `claude` is installed and
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
from core.providers.claude_code_cli_provider import ClaudeCodeCliProvider
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskMode, TaskStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AI_TESTS") != "true" or shutil.which("claude") is None,
    reason="Live Stage 3 event test: set RUN_LIVE_AI_TESTS=true with `claude` installed to run.",
)


async def test_a_real_claude_code_cli_task_publishes_the_real_events_the_office_translates(
    tmp_path: Path,
) -> None:
    status = await ClaudeCodeCliProvider().get_status()
    if status.state != ProviderConnectionState.CONNECTED:
        pytest.skip(f"claude CLI is installed but not authenticated ({status.detail!r}).")

    ctx = await build_context(
        tmp_path / "stage3_live_claude.db", secret_store=InMemorySecretStore(), detect_cli_providers=True,
    )
    try:
        events: list[OrchestrationEvent] = []
        ctx.event_bus.subscribe(lambda e: events.append(e))

        project = await ctx.project_service.create_project(ProjectCreate(name="Stage 3 Live Event Test (Claude)"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id,
                title="Reply with exactly the text PROBE_OK, using no tools.",
                mode=TaskMode.MANUAL,
                input={"agent_id": "agent_claude_code_architect", "risk": "low"},
            )
        )

        execution = await ctx.engine.run(task)

        assert execution.status == ExecutionStatus.COMPLETED
        final_task = await ctx.task_service.get_task(task.id)
        assert final_task.status == TaskStatus.COMPLETED

        selected = [e for e in events if e.type == EventType.AGENT_SELECTED]
        assert any(
            e.payload.get("agent_id") == "agent_claude_code_architect"
            and e.payload.get("provider") == "claude_code_cli"
            for e in selected
        )

        completed = [e for e in events if e.type == EventType.STEP_COMPLETED and "agent_id" in e.payload]
        work_completion = next(e for e in completed if e.payload.get("agent_id") == "agent_claude_code_architect")
        assert work_completion.payload["provider"] == "claude_code_cli"
        assert work_completion.payload["success"] is True

        assert any(e.type == EventType.EXECUTION_COMPLETED for e in events)
    finally:
        await ctx.close()
