"""Opt-in real authenticated CLI vertical acceptance, against a disposable Git repo."""
from __future__ import annotations

import os

import pytest
from core.bridge.context import build_context
from core.missions.models import MissionCommand, MissionCreate
from core.projects.models import ProjectCreate
from core.security.secret_store import InMemorySecretStore
from core.utils.shell_runner import get_runner


@pytest.mark.skipif(os.getenv('RUN_LIVE_MISSION_TESTS') != '1', reason='Real CLI credentials/cost opt-in')
async def test_real_cli_mission(tmp_path):
    project_dir = tmp_path / 'workspace'
    project_dir.mkdir()
    (project_dir / 'increment.py').write_text('def increment(value):\n    return value + 2\n')
    (project_dir / 'test_increment.py').write_text('from increment import increment\ndef test_increment():\n    assert increment(4) == 5\n    assert increment(-1) == 0\n')
    (project_dir / 'pyproject.toml').write_text('[project]\nname="mission-fixture"\nversion="0.1.0"\n')
    await get_runner().run(['git', 'init'], cwd=project_dir)
    ctx = await build_context(tmp_path / 'live.db', secret_store=InMemorySecretStore())
    try:
        service = ctx.mission_service
        assert service
        # Select only the explicitly requested live provider in this disposable DB.
        provider = os.getenv('LIVE_MISSION_PROVIDER', 'codex_cli')
        for agent in await ctx.agents_repo.list():
            if agent.provider != provider:
                await ctx.agents_repo.upsert(agent.model_copy(update={'active': False}))
        project = await ctx.project_service.create_project(ProjectCreate(name='Live acceptance', workspace_path=str(project_dir)))
        mission = await service.create(MissionCreate(project_id=project.id, command_id='live-create',
            request='Fix increment.py: increment(value) must return value + 1. Preserve test_increment.py unchanged. '
                    'One small coding task only; use capability coding. Do not commit or install anything.'))
        await service.command(MissionCommand(mission_id=mission.id, command_id='live-plan', action='analyze'))
        await service.wait(mission.id)
        snap = await service.repo.snapshot(mission.id)
        print('LIVE PLAN:', snap.mission.status, snap.mission.reason)
        assert snap.mission.status == 'planned', snap.mission.reason
        await service.command(MissionCommand(mission_id=mission.id, command_id='live-start', action='start'))
        await service.wait(mission.id)
        snap = await service.repo.snapshot(mission.id)
        print('LIVE RESULT:', snap.mission.status, snap.mission.reason)
        print('LIVE EVIDENCE:', len(snap.sessions), 'sessions;', len(snap.messages), 'messages;', len(snap.events), 'events')
        assert snap.mission.status == 'completed', snap.mission.reason
        assert snap.reviews[-1].verdict == 'approval'
        assert any(a.kind == 'test' and a.exit_code == 0 for a in snap.artifacts)
        assert len({a.agent_id for a in snap.assignments}) >= 3
        assert all(s.external_session_id for s in snap.sessions)
        assert 'value + 1' in (project_dir / 'increment.py').read_text()
        before = snap
        await ctx.close()
        ctx = await build_context(tmp_path / 'live.db', secret_store=InMemorySecretStore())
        assert ctx.mission_service
        after = await ctx.mission_service.repo.snapshot(mission.id)
        assert after == before
    finally:
        await ctx.close()
