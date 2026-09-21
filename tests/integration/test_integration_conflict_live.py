"""Opt-in real Codex conflict-resolution smoke test.

This test is intentionally excluded from normal CI: it starts four real CLI
sessions and requires a local authenticated Codex installation.
"""
from __future__ import annotations

import os

import pytest
from core.bridge.context import build_context
from core.integration.models import QualityGateDefinition, QualityGateProfile
from core.missions.models import MissionCommand, MissionCreate
from core.projects.models import ProjectCreate
from core.security.secret_store import InMemorySecretStore
from core.utils.ids import new_id
from core.utils.shell_runner import get_runner
from core.utils.time import utc_now


@pytest.mark.skipif(os.getenv("RUN_LIVE_INTEGRATION_CONFLICT_TESTS") != "1", reason="Real conflict CLI opt-in")
async def test_real_codex_assisted_conflict_resolution(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "shared_contract.py").write_text("VERSION = 1\n\ndef backend_value():\n    return 1\n\ndef frontend_label():\n    return 'old'\n")
    (workspace / "test_contract.py").write_text("from shared_contract import VERSION, backend_value, frontend_label\n\ndef test_contract():\n    assert VERSION == 2\n    assert backend_value() == 2\n    assert frontend_label() == 'new'\n")
    (workspace / "pyproject.toml").write_text('[project]\nname="conflict-fixture"\nversion="0.1.0"\n')
    await get_runner().run(["git", "init", "-b", "main"], cwd=workspace)
    await get_runner().run(["git", "config", "user.email", "test@example.invalid"], cwd=workspace)
    await get_runner().run(["git", "config", "user.name", "AgentMash Conflict Live"], cwd=workspace)
    await get_runner().run(["git", "add", "."], cwd=workspace)
    await get_runner().run(["git", "commit", "-qm", "base"], cwd=workspace)
    base_sha = (await get_runner().run(["git", "rev-parse", "HEAD"], cwd=workspace)).stdout.strip()
    ctx = await build_context(tmp_path / "conflict.db", secret_store=InMemorySecretStore())
    try:
        for agent in await ctx.agents_repo.list():
            if agent.provider != "codex_cli":
                await ctx.agents_repo.upsert(agent.model_copy(update={"active": False}))
        project = await ctx.project_service.create_project(ProjectCreate(name="Conflict live", workspace_path=str(workspace)))
        agents = await ctx.agents_repo.list()
        assert {"Atlas", "Nova", "Vega", "Sentinel"} <= {a.name.rsplit(" ", 1)[-1] for a in agents if a.provider == "codex_cli"}
        service = ctx.mission_service
        assert service
        profile = QualityGateProfile(id=new_id("profile"), project_id=project.id, name="full", is_default=True,
            gates=[QualityGateDefinition(id="pytest", name="pytest", argv=["python", "-m", "pytest", "-q"], kind="test", source="user")], created_at=utc_now(), updated_at=utc_now())
        await ctx.integration_repo.save_profile(profile)
        mission = await service.create(MissionCreate(project_id=project.id, command_id="conflict-create",
            request="Atlas and Nova must independently edit the same shared_contract.py contract. Atlas implements backend_value returning 2 and Nova implements frontend_label returning new, both changing VERSION to 2. Keep both behaviors after integration, create a real Git conflict, and do not alter main."))
        await service.command(MissionCommand(mission_id=mission.id, command_id="conflict-plan", action="analyze"))
        await service.wait(mission.id)
        planned = await service.repo.snapshot(mission.id)
        assert planned.mission.status == "planned", planned.mission.reason
        assert len(planned.plans[-1].tasks) >= 2
        await service.command(MissionCommand(mission_id=mission.id, command_id="conflict-start", action="start"))
        await service.wait(mission.id)
        blocked = await service.repo.snapshot(mission.id)
        assert blocked.mission.status == "blocked", blocked.mission.reason
        assert blocked.conflicts, f"Git conflict was not persisted: {blocked.mission.reason}; integrations={blocked.integrations}; tasks={[t.status for t in blocked.tasks]}"
        conflict = blocked.conflicts[0]
        agents_by_name = {a.name.rsplit(" ", 1)[-1]: a for a in agents if a.provider == "codex_cli"}
        result = await service.assist_conflict(mission.id, conflict.id, agents_by_name["Vega"].id, agents_by_name["Sentinel"].id)
        assert result["status"] == "awaiting_human_approval"
        after = await service.repo.snapshot(mission.id)
        assert after.conflicts[0].status == "awaiting_human_approval"
        attempts = await ctx.integration_repo.attempts(conflict.id)
        assert attempts[-1].commit_sha and attempts[-1].resolution_branch
        assert any(m.message_type == "question" and m.reply_to is None for m in after.messages)
        await service.approve_conflict(conflict.id, "Aprovado após review e quality gate")
        resolved = await service.repo.snapshot(mission.id)
        assert resolved.conflicts[0].status == "resolved"
        assert (await get_runner().run(["git", "rev-parse", "HEAD"], cwd=workspace)).stdout.strip() == base_sha
        await ctx.close()
        ctx = await build_context(tmp_path / "conflict.db", secret_store=InMemorySecretStore())
        recovered = await ctx.mission_service.repo.snapshot(mission.id)
        assert recovered.conflicts[0].status == "resolved"
    finally:
        await ctx.close()
