"""Deterministic collaboration tests. Scripted model output is a test seam only."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.missions.models import (
    MissionCommand,
    MissionCreate,
    PlanOutput,
    parse_output,
)
from core.missions.runtime import MissionRuntime
from core.missions.selection import choose_agent
from core.missions.service import MissionBlocked
from core.projects.models import ProjectCreate
from core.providers.base import AIResponse, TokenUsage
from core.security.secret_store import InMemorySecretStore
from core.sessions.models import SessionStatus
from core.utils.errors import CancelledErrorX, DatabaseError, ValidationError
from core.utils.shell_runner import get_runner
from pydantic import ValidationError as PydanticValidationError

PLAN = {'summary': 'Implement a small change', 'tasks': [
    {'key': 'implementation', 'title': 'Implement', 'description': 'Implement requested change',
     'capabilities': ['coding'], 'acceptance': ['Tests pass']}], 'limitations': []}
PARALLEL_PLAN = {'summary': 'Implement two independent changes', 'tasks': [
    {'key': 'backend', 'title': 'Backend change', 'description': 'Implement the backend change',
     'capabilities': ['coding'], 'acceptance': ['Tests pass'], 'expected_paths': ['backend.py']},
    {'key': 'frontend', 'title': 'Frontend change', 'description': 'Implement the frontend change',
     'capabilities': ['coding'], 'acceptance': ['Tests pass'], 'expected_paths': ['frontend.py']}], 'limitations': []}
WORK = {'summary': 'Implemented', 'files': ['result.txt'], 'limitations': []}
APPROVE = {'verdict': 'approval', 'justification': 'Inspected the implementation against criteria'}
CHANGES = {'verdict': 'changes_requested', 'justification': 'Handle empty input',
           'challenges': ['Why is empty input not handled?']}


class ScriptedRuntime(MissionRuntime):
    def __init__(self, manager, outputs):
        super().__init__(manager)
        self.outputs = list(outputs)
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.slow = False
        self.cancelled = False

    async def connected(self):
        return {'codex_cli', 'claude_code_cli'}

    async def execute(self, session, agent, prompt, **kwargs):
        self.calls.append((session, agent, prompt, kwargs))
        self.started.set()
        if self.slow:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            if self.cancelled:
                raise CancelledErrorX('cancelled')
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return AIResponse(content=json.dumps(value), provider=agent.provider, model='test',
            finish_reason='stop', usage=TokenUsage(), duration_seconds=0,
            structured_output={'thread_id': f'external-{session.id}'})

    async def cancel(self, session, agent):
        self.cancelled = True
        self.release.set()


@pytest_asyncio.fixture
async def mission_env(tmp_path):
    workspace = tmp_path / 'project'
    workspace.mkdir()
    from core.utils.shell_runner import get_runner
    await get_runner().run(['git', 'init'], cwd=workspace)
    (workspace / 'pyproject.toml').write_text('[project]\nname="test-project"\nversion="0.1.0"\n')
    (workspace / 'test_example.py').write_text('def test_real_validation():\n    assert 2 + 2 == 4\n')
    await get_runner().run(['git', 'config', 'user.email', 'test@example.invalid'], cwd=workspace)
    await get_runner().run(['git', 'config', 'user.name', 'AgentMash Test'], cwd=workspace)
    await get_runner().run(['git', 'add', '.'], cwd=workspace)
    await get_runner().run(['git', 'commit', '-qm', 'fixture'], cwd=workspace)
    ctx = await build_context(tmp_path / 'missions.db', secret_store=InMemorySecretStore())
    project = await ctx.project_service.create_project(ProjectCreate(name='Project', workspace_path=str(workspace)))
    service = ctx.mission_service
    assert service
    runtime = ScriptedRuntime(ctx.provider_manager, [PLAN, WORK, APPROVE])
    service.runtime = runtime
    mission = await service.create(MissionCreate(project_id=project.id, request='Implement', command_id='create'))
    try:
        yield ctx, service, runtime, mission
    finally:
        await ctx.close()


async def action(service, mission, action, **kwargs):
    await service.command(MissionCommand(mission_id=mission.id, command_id=f'{action}-{len(service.jobs)}-{kwargs}',
                                        action=action, **kwargs))
    await service.wait(mission.id)


async def test_full_mission_correction_and_real_tests(mission_env):
    ctx, service, runtime, mission = mission_env
    runtime.outputs = [PLAN, WORK, CHANGES, WORK, APPROVE]
    await action(service, mission, 'analyze')
    planned = await service.repo.snapshot(mission.id)
    assert planned.mission.status == 'planned'
    assert len(planned.plans[0].choices) == 3
    assert len({c.agent_id for c in planned.plans[0].choices}) == 3
    await action(service, mission, 'start')
    result = await service.repo.snapshot(mission.id)
    assert result.mission.status == 'completed', result.mission.reason
    assert [r.verdict for r in result.reviews] == ['changes_requested', 'approval']
    assert {'handoff', 'review_request', 'review_challenge', 'changes_requested', 'fix_response', 'approval'} <= {m.message_type for m in result.messages}
    assert any(m.delivery_status == 'delivered' for m in result.messages)
    assert any(a.kind == 'test' and a.exit_code == 0 and 'passed' in a.content for a in result.artifacts)
    assert all(s.external_session_id for s in result.sessions)
    assert all(s.project_id == mission.project_id for s in result.sessions)
    assert 'Handle empty input' in runtime.calls[3][2]
    assert runtime.calls[2][3]['writable'] is False
    assert runtime.calls[1][3]['writable'] is True
    assert 'arquivos' in result.mission.result.lower() or 'Arquivos' in result.mission.result
    assert len(result.events) == len({e.sequence for e in result.events})
    await ctx.db.execute('PRAGMA foreign_key_check')


async def test_parallel_mission_uses_isolated_worktrees_and_human_gate(mission_env):
    ctx, service, runtime, mission = mission_env
    runtime.outputs = [PARALLEL_PLAN, WORK, WORK, CHANGES, APPROVE, WORK, APPROVE]
    await action(service, mission, 'analyze')
    await action(service, mission, 'start')
    snap = await service.repo.snapshot(mission.id)
    assert snap.mission.status == 'awaiting_human_approval', snap.mission.reason
    assert len(snap.worktrees) == 2
    assert len({w.path for w in snap.worktrees}) == 2
    assert len({w.branch_name for w in snap.worktrees}) == 2
    assert len(snap.integrations) == 2
    assert snap.quality_gates and snap.quality_gates[-1].passed
    assert any(r.verdict == 'changes_requested' for r in snap.reviews)
    assert any(m.message_type == 'changes_requested' for m in snap.messages)
    main_sha = (await get_runner().run(['git', 'rev-parse', 'HEAD'], cwd=Path(await service.workspace(mission)))).stdout.strip()
    await action(service, mission, 'approve', content='Aprovado para integração manual futura.')
    approved = await service.repo.get(type(mission), mission.id)
    assert approved.status == 'completed'
    assert (await get_runner().run(['git', 'rev-parse', 'HEAD'], cwd=Path(await service.workspace(mission)))).stdout.strip() == main_sha


async def test_mission_restore_and_create_idempotency(mission_env):
    ctx, service, runtime, mission = mission_env
    duplicate = await service.create(MissionCreate(project_id=mission.project_id, request='Implement', command_id='create'))
    assert duplicate.id == mission.id
    await action(service, mission, 'analyze')
    db_path = ctx.db.db_path
    before = await service.repo.snapshot(mission.id)
    await ctx.close()
    reopened = await build_context(db_path, secret_store=InMemorySecretStore())
    try:
        assert reopened.mission_service
        after = await reopened.mission_service.repo.snapshot(mission.id)
        assert after == before
    finally:
        await reopened.close()


@pytest.mark.parametrize('bad', [
    {'summary': 'x', 'tasks': []},
    {**PLAN, 'tasks': [*PLAN['tasks'], *PLAN['tasks']]},
    {**PLAN, 'tasks': [{**PLAN['tasks'][0], 'depends_on': ['missing']}]},
    {**PLAN, 'tasks': [{**PLAN['tasks'][0], 'depends_on': ['implementation']}]},
    {**PLAN, 'unexpected': True},
])
def test_plan_rejects_invalid_graph_or_schema(bad):
    with pytest.raises(PydanticValidationError):
        parse_output(json.dumps(bad), PlanOutput)


def test_plan_accepts_fenced_json():
    assert parse_output('```json\n' + json.dumps(PLAN) + '\n```', PlanOutput).tasks[0].key == 'implementation'


async def test_selection_deterministic_and_independent(mission_env):
    ctx, service, runtime, mission = mission_env
    agents = await ctx.agents_repo.list()
    args = dict(role='reviewer', connected={'codex_cli', 'claude_code_cli'}, project_id=mission.project_id,
                excluded=set(), busy=set())
    first = choose_agent(agents, **args)
    assert first == choose_agent(list(reversed(agents)), **args)
    assert first.reason
    with pytest.raises(ValidationError):
        choose_agent(agents, **{**args, 'connected': set()})
    await action(service, mission, 'analyze')
    await action(service, mission, 'start')
    snap = await service.repo.snapshot(mission.id)
    review = snap.reviews[0]
    with pytest.raises(DatabaseError):
        await service.repo.put(review.model_copy(update={'id': 'invalid-review',
            'reviewer_session_id': review.worker_session_id}))


async def test_events_immutable_and_messages_scoped(mission_env):
    ctx, service, runtime, mission = mission_env
    await action(service, mission, 'analyze')
    with pytest.raises(DatabaseError):
        await ctx.db.execute('UPDATE mission_events SET entity_type=?', ('fake',))
    with pytest.raises(ValidationError):
        await service.message(mission.id, 'foreign-session', None, 'question', 'hi')


async def test_instruction_during_work_is_decided_by_leader(mission_env):
    ctx, service, runtime, mission = mission_env
    await action(service, mission, 'analyze')
    runtime.outputs = [
        {'disposition': 'context_share', 'reason': 'Complements acceptance'}, WORK, APPROVE]
    await service.command(MissionCommand(mission_id=mission.id, command_id='extra', action='instruction', content='Also document it'))
    await action(service, mission, 'start')
    snap = await service.repo.snapshot(mission.id)
    assert snap.mission.status == 'completed', snap.mission.reason
    assert snap.instructions[0].disposition == 'context_share'
    assert 'Also document it' in runtime.calls[-1][2]


async def test_crash_recovery_never_claims_completion(mission_env):
    ctx, service, runtime, mission = mission_env
    await action(service, mission, 'analyze')
    session = (await service.repo.snapshot(mission.id)).sessions[0]
    await service.repo.sessions.update_status(session.id, SessionStatus.WORKING)
    await service.status(mission.id, 'running')
    await service.recover()
    snap = await service.repo.snapshot(mission.id)
    assert snap.mission.status == 'blocked'
    assert snap.sessions[0].status == SessionStatus.INTERRUPTED
    assert 'reiniciada' in snap.mission.reason


async def test_cancel_active_cli_and_persist_states(mission_env):
    ctx, service, runtime, mission = mission_env
    runtime.slow = True
    await service.command(MissionCommand(mission_id=mission.id, command_id='analyze', action='analyze'))
    await asyncio.wait_for(runtime.started.wait(), 3)
    await service.command(MissionCommand(mission_id=mission.id, command_id='cancel', action='cancel'))
    snap = await service.repo.snapshot(mission.id)
    assert runtime.cancelled
    assert snap.mission.status == 'cancelled'
    assert all(s.status == SessionStatus.CANCELLED for s in snap.sessions)


@pytest.mark.parametrize('failure', [TimeoutError('CLI timeout'), MissionBlocked('Credentials missing')])
async def test_failure_is_blocked_not_fake_success(mission_env, failure):
    ctx, service, runtime, mission = mission_env
    runtime.outputs = [failure]
    await action(service, mission, 'analyze')
    snap = await service.repo.snapshot(mission.id)
    assert snap.mission.status == 'blocked'
    assert str(failure) in snap.mission.reason


async def test_missing_tests_blocks_final_result(mission_env):
    ctx, service, runtime, mission = mission_env
    workspace = Path(await service.workspace(mission))
    (workspace / 'pyproject.toml').unlink()
    await action(service, mission, 'analyze')
    await action(service, mission, 'start')
    snap = await service.repo.snapshot(mission.id)
    assert snap.mission.status == 'blocked'
    assert 'testes' in snap.mission.reason


async def test_bridge_validates_commands(mission_env):
    ctx, service, runtime, mission = mission_env
    with pytest.raises(PydanticValidationError):
        await dispatch('mission.command', {'mission_id': mission.id, 'command_id': 'bad', 'action': 'complete'}, ctx)
    result = await dispatch('mission.get', {'mission_id': mission.id}, ctx)
    assert result['mission']['id'] == mission.id


async def test_new_request_arrives_while_worker_is_running(mission_env):
    ctx, service, runtime, mission = mission_env
    await action(service, mission, 'analyze')
    runtime.started.clear()
    runtime.slow = True
    runtime.outputs = [WORK, APPROVE, {'disposition': 'queued', 'reason': 'Independent follow-up'}]
    await service.command(MissionCommand(mission_id=mission.id, command_id='start-live', action='start'))
    await asyncio.wait_for(runtime.started.wait(), 3)
    await service.command(MissionCommand(mission_id=mission.id, command_id='during', action='instruction', content='Research another feature later'))
    assert (await service.repo.snapshot(mission.id)).instructions[0].disposition == 'pending'
    runtime.slow = False
    runtime.release.set()
    await service.wait(mission.id)
    result = await service.repo.snapshot(mission.id)
    assert result.mission.status == 'completed', result.mission.reason
    assert result.instructions[0].disposition == 'queued'


async def test_question_and_answer_reach_worker_context(mission_env):
    ctx, service, runtime, mission = mission_env
    runtime.outputs = [PLAN, {**WORK, 'question': 'Which input should be supported?'},
                       {**WORK, 'summary': 'Support empty input too'}, WORK, APPROVE]
    await action(service, mission, 'analyze')
    await action(service, mission, 'start')
    snap = await service.repo.snapshot(mission.id)
    assert snap.mission.status == 'completed', snap.mission.reason
    assert {'question', 'answer'} <= {m.message_type for m in snap.messages}
    assert 'Support empty input too' in runtime.calls[3][2]


async def test_pause_then_resume_preserves_mission(mission_env):
    ctx, service, runtime, mission = mission_env
    await action(service, mission, 'analyze')
    runtime.started.clear()
    runtime.slow = True
    await service.command(MissionCommand(mission_id=mission.id, command_id='run-pause', action='start'))
    await asyncio.wait_for(runtime.started.wait(), 3)
    await service.command(MissionCommand(mission_id=mission.id, command_id='pause', action='pause'))
    snap = await service.repo.snapshot(mission.id)
    assert snap.mission.status == 'blocked'
    assert any(s.status == SessionStatus.PAUSED for s in snap.sessions)
    runtime.slow = False
    runtime.cancelled = False
    runtime.outputs = [WORK, APPROVE]
    await action(service, mission, 'resume')
    snap = await service.repo.snapshot(mission.id)
    assert snap.mission.status == 'completed', snap.mission.reason


async def test_writer_lease_excludes_nested_projects(mission_env):
    ctx, service, runtime, mission = mission_env
    other = await service.create(MissionCreate(project_id=mission.project_id, request='Other', command_id='other'))
    path = await service.workspace(mission)
    assert await service.repo.lease(path, mission.id)
    assert not await service.repo.lease(str(Path(path) / 'subproject'), other.id)
    await service.repo.release(mission.id)
    assert await service.repo.lease(path, other.id)


async def test_seed_does_not_overwrite_persistent_agent_settings(mission_env):
    ctx, service, runtime, mission = mission_env
    agent = (await ctx.agents_repo.list())[0]
    modified = agent.model_copy(update={'system_prompt': 'My instructions', 'active': False})
    await ctx.agents_repo.upsert(modified)
    await ctx.agents_repo.seed_defaults([agent])
    assert await ctx.agents_repo.get(agent.id) == modified


async def test_timeout_stops_pending_call(mission_env):
    ctx, service, runtime, mission = mission_env
    service.session_timeout = .05
    runtime.slow = True
    await action(service, mission, 'analyze')
    snap = await service.repo.snapshot(mission.id)
    assert runtime.cancelled
    assert snap.mission.status == 'blocked'
    assert 'Timeout' in snap.mission.reason


async def test_reassign_rejects_reviewer_and_accepts_other_worker(mission_env):
    ctx, service, runtime, mission = mission_env
    await action(service, mission, 'analyze')
    runtime.outputs = [WORK, {'verdict': 'human_input_required', 'justification': 'Clarify scope'}]
    await action(service, mission, 'start')
    snap = await service.repo.snapshot(mission.id)
    reviewer = next(a for a in snap.assignments if a.role == 'reviewer')
    with pytest.raises(ValidationError):
        await service.command(MissionCommand(mission_id=mission.id, command_id='bad-reassign', action='reassign',
                                            agent_id=reviewer.agent_id, task_id=snap.tasks[0].id))
    worker = next(a for a in await ctx.agents_repo.list() if a.provider == 'codex_cli' and a.permissions.can_write_files)
    await service.command(MissionCommand(mission_id=mission.id, command_id='good-reassign', action='reassign',
                                        agent_id=worker.id, task_id=snap.tasks[0].id))
    updated = await service.repo.snapshot(mission.id)
    assert any(a.agent_id == worker.id and a.active and a.task_id == snap.tasks[0].id for a in updated.assignments)
