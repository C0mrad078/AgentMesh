"""Opt-in real Codex parallel-worktree smoke test on a disposable repository."""
from __future__ import annotations

import os

import pytest
from core.bridge.context import build_context
from core.missions.models import MissionCommand, MissionCreate
from core.projects.models import ProjectCreate
from core.security.secret_store import InMemorySecretStore
from core.utils.shell_runner import get_runner


@pytest.mark.skipif(os.getenv("RUN_LIVE_PARALLEL_MISSION_TESTS") != "1", reason="Real CLI opt-in")
async def test_real_parallel_codex_worktrees(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "backend.py").write_text("def value():\n    return 1\n")
    (workspace / "frontend.py").write_text("def label():\n    return 'old'\n")
    (workspace / "test_backend.py").write_text("from backend import value\ndef test_value(): assert value() == 2\n")
    (workspace / "test_frontend.py").write_text("from frontend import label\ndef test_label(): assert label() == 'new'\n")
    (workspace / "pyproject.toml").write_text('[project]\nname="parallel-fixture"\nversion="0.1.0"\n')
    await get_runner().run(["git", "init", "-b", "main"], cwd=workspace)
    await get_runner().run(["git", "config", "user.email", "test@example.invalid"], cwd=workspace)
    await get_runner().run(["git", "config", "user.name", "AgentMash Live"], cwd=workspace)
    await get_runner().run(["git", "add", "."], cwd=workspace)
    await get_runner().run(["git", "commit", "-qm", "base"], cwd=workspace)
    base_sha = (await get_runner().run(["git", "rev-parse", "HEAD"], cwd=workspace)).stdout.strip()
    ctx = await build_context(tmp_path / "parallel.db", secret_store=InMemorySecretStore())
    try:
        for agent in await ctx.agents_repo.list():
            if agent.provider != "codex_cli":
                await ctx.agents_repo.upsert(agent.model_copy(update={"active": False}))
        project = await ctx.project_service.create_project(ProjectCreate(name="Parallel live", workspace_path=str(workspace)))
        service = ctx.mission_service
        assert service
        mission = await service.create(MissionCreate(project_id=project.id, command_id="parallel-create",
            request="Implement exactly two independent improvements in parallel: update backend.py so value returns 2 and update frontend.py so label returns new. Keep each change isolated in its own worktree and run the tests. Do not alter main."))
        await service.command(MissionCommand(mission_id=mission.id, command_id="parallel-plan", action="analyze"))
        await service.wait(mission.id)
        planned = await service.repo.snapshot(mission.id)
        assert planned.mission.status == "planned", planned.mission.reason
        assert len(planned.plans[-1].tasks) >= 2
        await service.command(MissionCommand(mission_id=mission.id, command_id="parallel-start", action="start"))
        await service.wait(mission.id)
        result = await service.repo.snapshot(mission.id)
        assert result.mission.status == "awaiting_human_approval", result.mission.reason
        assert len(result.worktrees) >= 2
        assert len({w.path for w in result.worktrees}) >= 2
        assert len(result.integrations) >= 2
        assert any(r.verdict == "changes_requested" for r in result.reviews)
        assert result.quality_gates and all(g.passed for g in result.quality_gates)
        assert (await get_runner().run(["git", "rev-parse", "HEAD"], cwd=workspace)).stdout.strip() == base_sha
        await service.command(MissionCommand(mission_id=mission.id, command_id="parallel-approve", action="approve", content="Approved"))
        await service.wait(mission.id)
        approved = await service.repo.snapshot(mission.id)
        assert approved.mission.status == "completed"
        await ctx.close()
        ctx = await build_context(tmp_path / "parallel.db", secret_store=InMemorySecretStore())
        assert await ctx.mission_service.repo.snapshot(mission.id) == approved
    finally:
        await ctx.close()
