"""Genuinely live: same rationale as `test_cli_provider_pipeline_live.py`,
for the Claude Code CLI agent instead of Codex."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.orchestrator.models import ExecutionStatus
from core.projects.models import ProjectCreate
from core.providers.base import ProviderConnectionState
from core.providers.claude_code_cli_provider import ClaudeCodeCliProvider
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskMode, TaskStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AI_TESTS") != "true" or shutil.which("claude") is None,
    reason="Live CLI-provider pipeline test: set RUN_LIVE_AI_TESTS=true with `claude` installed to run.",
)


async def test_a_task_explicitly_routed_to_claude_code_cli_completes_through_the_real_engine(
    tmp_path: Path,
) -> None:
    status = await ClaudeCodeCliProvider().get_status()
    if status.state != ProviderConnectionState.CONNECTED:
        pytest.skip(f"claude CLI is installed but not authenticated ({status.detail!r}).")

    ctx = await build_context(
        tmp_path / "claude_cli_pipeline.db", secret_store=InMemorySecretStore(), detect_cli_providers=True,
    )
    try:
        assert ctx.provider_pool.is_registered("claude_code_cli"), (
            "build_context(detect_cli_providers=True) should have registered claude_code_cli "
            "since get_status() just confirmed it's connected."
        )

        project = await ctx.project_service.create_project(
            ProjectCreate(name="Claude Code CLI Live Pipeline Test")
        )
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
        assert final_task.result is not None

        steps = await ctx.steps_repo.list_for_execution(execution.id)
        phase_steps = [s for s in steps if s.kind == "phase"]
        assert all(s.status.value == "completed" for s in phase_steps)
    finally:
        await ctx.close()
