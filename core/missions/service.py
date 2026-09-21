"""Collaborative mission coordinator. Reuses repositories, CLI adapters and tools.

One supervised coroutine per mission. Agents produce plans and review decisions;
the backend enforces eligibility, dependencies, independence and bounded repairs.
No successful state can be manufactured by a frontend command.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from core.database.repositories.missions_repo import MissionsRepository
from core.integration.models import (
    ConflictFile,
    IntegrationConflict,
    IntegrationProposal,
    ResolutionAttempt,
    ResolutionDecision,
    ResolutionReview,
    classify_conflict,
)
from core.integration.quality_gates import validate_gate
from core.missions.evidence import describe_changes, snapshot_files
from core.missions.models import (
    AgentMessage,
    Artifact,
    Assignment,
    Choice,
    FileEvidence,
    Instruction,
    InstructionDecision,
    MessageType,
    Mission,
    MissionCommand,
    MissionCreate,
    MissionPlan,
    MissionStatus,
    PlanOutput,
    Review,
    ReviewOutput,
    Role,
    WorkerOutput,
    parse_output,
)
from core.missions.runtime import PROVIDER_IDS, MissionRuntime
from core.missions.selection import choose_agent
from core.orchestrator.event_bus import EventType, OrchestrationEvent
from core.parallel.concurrency import ParallelConcurrency
from core.parallel.forecast import forecast
from core.parallel.models import ConcurrencyLease, HumanApproval, IntegrationAttempt, QualityGateRun
from core.parallel.worktrees import WorktreeManager
from core.runtime.execution_backend import ExecutionBackendType
from core.security.secret_scanner import SecretScanner
from core.sessions.models import Session, SessionCreate, SessionStatus
from core.tasks.models import TaskCreate, TaskStatus
from core.tools.command_planner import CommandPlanner, ProjectAction
from core.tools.git_tool import GitTool
from core.utils.errors import CancelledErrorX, ValidationError
from core.utils.ids import new_id
from core.utils.process_observer import ProcessObservation, process_observer
from core.utils.shell_runner import get_runner, process_is_alive
from core.utils.time import utc_now

if TYPE_CHECKING:
    from core.bridge.context import BridgeContext

T = TypeVar('T', bound=BaseModel)
TERMINAL = {'completed', 'failed', 'cancelled'}
ACTIVE = {'analyzing', 'running', 'reviewing', 'changes_requested', 'testing'}


class MissionBlocked(Exception):
    pass


class HumanInputRequired(MissionBlocked):
    pass


class MissionService:
    def __init__(self, ctx: BridgeContext) -> None:
        self.ctx = ctx
        self.repo = MissionsRepository(ctx.db)
        self.runtime = MissionRuntime(ctx.provider_manager)
        self.jobs: dict[str, asyncio.Task[None]] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.session_timeout = 300.0
        self.max_review_rounds = 3
        self._cursor: dict[str, int] = {}
        self._commands = asyncio.Lock()
        self.workspace_gate = asyncio.Lock()
        self._agents_in_flight: set[str] = set()
        self.legacy_workspaces: set[str] = set()
        self.parallel = ParallelConcurrency()
        self.worktrees = WorktreeManager(ctx.parallel_repo)
        self.review_gate = asyncio.Lock()

    def clean(self, text: str) -> str:
        return SecretScanner().redact(text)[0]

    async def notify(self, mission_id: str) -> None:
        for event in await self.repo.events(mission_id, self._cursor.get(mission_id, 0)):
            await self.ctx.event_bus.publish(OrchestrationEvent(
                type=EventType.MISSION_CHANGED, execution_id='',
                payload=event.model_dump(mode='json')))
            self._cursor[mission_id] = event.sequence

    async def status(self, mission_id: str, status: MissionStatus, reason: str = '', result: str = '') -> None:
        current = await self.repo.get(Mission, mission_id)
        await self.repo.put(current.model_copy(update={
            'status': status, 'reason': self.clean(reason),
            'result': self.clean(result) if result else current.result, 'updated_at': utc_now()}))
        await self.notify(mission_id)

    async def create(self, data: MissionCreate) -> Mission:
        async with self._commands:
            existing = await self.repo.by_command(data.command_id)
            if existing:
                if existing.project_id != data.project_id or existing.request != self.clean(data.request):
                    raise ValidationError('Command id already used for different mission')
                return existing
            await self.ctx.project_service.get_project(data.project_id)
            now = utc_now()
            mission = Mission(id=new_id('mission'), project_id=data.project_id,
                              request=self.clean(data.request), created_at=now, updated_at=now)
            await self.repo.put(mission, command_id=data.command_id)
            await self.notify(mission.id)
            return mission

    async def command(self, cmd: MissionCommand) -> Mission:
        async with self._commands:
            mission = await self.repo.get(Mission, cmd.mission_id)
            if not await self.repo.claim_command(cmd):
                return mission
            try:
                await self._command(mission, cmd)
            except Exception:
                await self.repo.finish_command(cmd.command_id, failed=True)
                raise
            await self.repo.finish_command(cmd.command_id)
            await self.notify(mission.id)
            return await self.repo.get(Mission, mission.id)

    async def _command(self, mission: Mission, cmd: MissionCommand) -> None:
        mid = mission.id
        if cmd.action == 'instruction':
            if not cmd.content.strip():
                raise ValidationError('Instrução vazia')
            if mission.status in TERMINAL:
                raise ValidationError('Crie outra missão para pedidos após conclusão')
            await self.repo.put(Instruction(id=new_id('instruction'), mission_id=mid,
                content=self.clean(cmd.content), created_at=utc_now()))
            return
        if cmd.action in ('cancel', 'pause'):
            if mission.status in TERMINAL:
                return
            if cmd.session_id:
                await self.repo.belongs('session', mid, cmd.session_id)
            await self.stop(mid, pause=cmd.action == 'pause', session_id=cmd.session_id)
            return
        if cmd.action == 'approve' and mission.status == 'awaiting_human_approval':
            if not cmd.content.strip():
                raise ValidationError('A aprovação humana precisa de uma justificativa.')
            await self.ctx.parallel_repo.add_approval(HumanApproval(
                id=new_id('approval'), mission_id=mid, decision='approved',
                rationale=self.clean(cmd.content), created_at=utc_now()))
            await self.status(mid, 'completed', 'Entrega aprovada para integração manual futura.')
            return
        if cmd.action == 'approve' and mission.status == 'awaiting_approval':
            if not cmd.content.strip():
                raise ValidationError('A decisão humana precisa de uma justificativa.')
            await self.ctx.parallel_repo.add_approval(HumanApproval(
                id=new_id('approval'), mission_id=mid, decision='approved',
                rationale=self.clean(cmd.content), created_at=utc_now()))
            await self.status(mid, 'changes_requested', self.clean(cmd.content))
            self.launch(mid, analyze=False)
            return
        if mission.status in TERMINAL:
            raise ValidationError('Missão encerrada')
        if cmd.action in ('include_agent', 'reassign'):
            if mid in self.jobs:
                raise ValidationError('Pause a missão antes de alterar a equipe')
            if not cmd.agent_id:
                raise ValidationError('Informe um agente')
            agent = await self.ctx.agents_repo.get(cmd.agent_id)
            if agent is None:
                raise ValidationError('Agente inexistente')
            task_id = cmd.task_id
            if task_id:
                await self.repo.belongs('task', mid, task_id)
                task = await self.repo.tasks.get_or_raise(task_id)
                if task.status == TaskStatus.COMPLETED:
                    raise ValidationError('Tarefa já concluída')
            elif cmd.action == 'reassign':
                raise ValidationError('Informe uma tarefa')
            assignments = await self.repo.list(Assignment, mid)
            reviewers = {a.agent_id for a in assignments if a.role == 'reviewer'}
            choice = choose_agent([agent], role='worker', connected=await self.runtime.connected(),
                project_id=mission.project_id, excluded=reviewers, busy=await self.busy(mid),
                required=['coding'])
            for a in assignments:
                if a.active and a.task_id == task_id and a.role == 'worker' and task_id:
                    await self.repo.put(a.model_copy(update={'active': False}))
            await self.new_session(mission, choice, task_id)
            return
        if mid in self.jobs:
            return  # start/analyze replay while running is idempotent, not a second process
        if cmd.action == 'analyze':
            if mission.status not in ('draft', 'blocked', 'planned', 'awaiting_approval'):
                raise ValidationError('Missão não pode ser analisada neste estado')
            self.launch(mid, analyze=True)
        elif cmd.action in ('start', 'resume'):
            if not mission.current_plan_id:
                raise ValidationError('Analise o pedido antes de iniciar')
            if mission.status not in ('planned', 'awaiting_approval', 'blocked'):
                raise ValidationError('Missão não pode iniciar neste estado')
            if mission.status == 'awaiting_approval' and cmd.action != 'approve':
                raise ValidationError('Registre uma decisão humana explícita antes de retomar.')
            if cmd.content.strip():
                await self.repo.put(Instruction(id=new_id('instruction'), mission_id=mid,
                    content=self.clean(cmd.content), created_at=utc_now()))
            self.launch(mid, analyze=False)
        else:
            raise ValidationError('Comando não suportado')

    def launch(self, mission_id: str, *, analyze: bool) -> None:
        self.cancel_events[mission_id] = asyncio.Event()
        self.jobs[mission_id] = asyncio.create_task(self._supervise(mission_id, analyze=analyze))

    async def wait(self, mission_id: str) -> None:
        job = self.jobs.get(mission_id)
        if job:
            await job

    async def workspace(self, mission: Mission) -> str:
        project = await self.ctx.project_service.get_project(mission.project_id)
        if not project.workspace_path:
            raise MissionBlocked('Projeto sem diretório configurado.')
        path = await asyncio.to_thread(Path(project.workspace_path).resolve)
        if not path.is_dir():
            raise MissionBlocked('Diretório do projeto indisponível.')
        return str(path)

    async def _supervise(self, mid: str, *, analyze: bool) -> None:
        try:
            mission = await self.repo.get(Mission, mid)
            path = await self.workspace(mission)
            for session in (await self.repo.snapshot(mid)).sessions:
                pid = session.metadata.get('process_id')
                if isinstance(pid, int) and process_is_alive(pid):
                    raise MissionBlocked(f'Processo anterior PID {pid} ainda existe. Encerre-o antes de retomar.')
            async with self.workspace_gate:
                if any(Path(path).is_relative_to(p) or Path(p).is_relative_to(path) for p in self.legacy_workspaces):
                    raise MissionBlocked('Execução clássica usa este diretório.')
                if not await self.repo.lease(path, mid):
                    raise MissionBlocked('Outro trabalho possui o diretório. Aguarde ou pause a outra missão.')
            # Legacy engine shares this workspace; do not overlap it either.
            tasks = await self.repo.tasks.list_for_project(mission.project_id)
            ours = {t.id for t in (await self.repo.snapshot(mid)).tasks}
            if any(t.id not in ours and t.status in (TaskStatus.RUNNING, TaskStatus.REVIEWING)
                   for t in tasks):
                raise MissionBlocked('Uma execução clássica está usando o projeto.')
            if analyze:
                await self.analyze(mid)
            else:
                await self.run(mid)
        except HumanInputRequired as exc:
            await self.status(mid, 'awaiting_approval', 'Decisão humana necessária: ' + str(exc))
        except (CancelledErrorX, asyncio.CancelledError):
            current = await self.repo.get(Mission, mid)
            if current.status not in ('blocked', 'cancelled'):
                await self.status(mid, 'blocked', 'Execução interrompida; retome explicitamente.')
        except Exception as exc:
            await self.status(mid, 'blocked', self.clean(str(exc))[:4000] or type(exc).__name__)
        finally:
            await self.repo.release(mid)
            await self.ctx.parallel_repo.release(mission_id=mid)
            self.jobs.pop(mid, None)
            self.cancel_events.pop(mid, None)
            await self.notify(mid)

    async def busy(self, mid: str) -> set[str]:
        return self._agents_in_flight | {s.agent_id for s in await self.repo.sessions.list_active()
                if s.metadata.get('mission_id') != mid and s.status in
                (SessionStatus.STARTING, SessionStatus.WORKING)}

    async def choose(self, mission: Mission, role: Role, excluded: set[str] | None = None,
                     required: list[str] | None = None) -> Choice:
        connected = await self.runtime.connected()
        connected = {p for p in connected if self.ctx.health_monitor.is_available(p)}
        return choose_agent(await self.ctx.agents_repo.list(), role=role, connected=connected,
            project_id=mission.project_id, excluded=excluded or set(), busy=await self.busy(mission.id),
            required=required)

    async def new_session(self, mission: Mission, choice: Choice, task_id: str | None = None,
                          *, workspace: str | None = None, isolation: str = "main") -> Session:
        agent = await self.ctx.agents_repo.get(choice.agent_id)
        if agent is None:
            raise MissionBlocked('Agente removido')
        provider = await self.ctx.providers_repo.get_by_name(PROVIDER_IDS[agent.provider])
        if provider is None:
            raise MissionBlocked('Provider ausente no catálogo')
        binding_id = agent.runtime_binding_id
        if binding_id is None:
            bindings = await self.ctx.runtime_bindings_repo.list(provider.id)
            binding_id = bindings[0].id if bindings else None
        session = await self.repo.sessions.create(SessionCreate(
            agent_id=agent.id, project_id=mission.project_id, provider_id=provider.id,
            runtime_binding_id=binding_id, backend_type=ExecutionBackendType.SUBSCRIPTION, task_id=task_id,
            metadata={'schema_version': 1, 'mission_id': mission.id, 'role': choice.role,
                      'workspace': workspace or await self.workspace(mission), 'isolation': isolation}))
        await self.repo.link('session', mission.id, session.id)
        await self.repo.put(Assignment(id=new_id('assignment'), mission_id=mission.id,
            task_id=task_id, agent_id=agent.id, session_id=session.id, role=choice.role,
            reason=choice.reason, created_at=utc_now()))
        if task_id and choice.role == 'worker':
            await self.repo.tasks.assign_session(task_id, session.id)
        await self.notify(mission.id)
        return session

    async def artifact(self, mid: str, kind: str, title: str, content: str,
                       session_id: str | None = None, task_id: str | None = None,
                       paths: list[str] | None = None, command: list[str] | None = None,
                       exit_code: int | None = None, files: list[FileEvidence] | None = None) -> Artifact:
        value = Artifact.model_validate(dict(id=new_id('artifact'), mission_id=mid, kind=kind,
            title=title, content=self.clean(content)[:100000], session_id=session_id, task_id=task_id,
            paths=paths or [], command=command or [], exit_code=exit_code, files=files or [], created_at=utc_now()))
        await self.repo.put(value)
        await self.notify(mid)
        return value

    async def message(self, mid: str, source: str, target: str | None, kind: MessageType,
                      content: str, task_id: str | None = None, reply_to: str | None = None,
                      artifacts: list[str] | None = None) -> AgentMessage:
        await self.repo.belongs('session', mid, source)
        if target:
            await self.repo.belongs('session', mid, target)
        if task_id:
            await self.repo.belongs('task', mid, task_id)
        if reply_to and (await self.repo.get(AgentMessage, reply_to)).mission_id != mid:
            raise ValidationError('Resposta pertence a outra missão')
        for aid in artifacts or []:
            if (await self.repo.get(Artifact, aid)).mission_id != mid:
                raise ValidationError('Artefato pertence a outra missão')
        msg = AgentMessage(id=new_id('message'), mission_id=mid, from_session_id=source,
            to_session_id=target, task_id=task_id, message_type=kind, content=self.clean(content)[:32000],
            artifact_ids=artifacts or [], reply_to=reply_to, timestamp=utc_now())
        await self.repo.put(msg)
        await self.notify(mid)
        return msg

    async def turn(self, mid: str, session: Session, prompt: str, model: type[T],
                   *, writable: bool = False) -> T:
        cancel = self.cancel_events.get(mid)
        if cancel and cancel.is_set():
            raise CancelledErrorX('Missão interrompida')
        limits = self.ctx.budget.limits
        if any(value is not None for value in (limits.max_per_execution_usd, limits.daily_limit_usd, limits.monthly_limit_usd)):
            raise MissionBlocked('Limite monetário configurado: este runtime CLI não oferece contabilidade garantida; execução bloqueada.')
        agent = await self.ctx.agents_repo.get(session.agent_id)
        if agent is None or not agent.active:
            raise MissionBlocked('Agente indisponível')
        if session.agent_id in await self.busy(mid):
            raise MissionBlocked('Agente ocupado em outra missão')
        mission = await self.repo.get(Mission, mid)
        messages = [m for m in await self.repo.list(AgentMessage, mid)
                    if m.to_session_id in (None, session.id)]
        instructions = [i for i in await self.repo.list(Instruction, mid)
                        if i.disposition == 'context_share']
        context = '\n'.join(f'{m.message_type}: {m.content}' for m in messages[-30:])
        context += '\n' + '\n'.join(i.content for i in instructions)
        prompt += '\nContexto recebido:\n' + context
        prompt += '\nJSON schema de saída:\n' + json.dumps(model.model_json_schema())
        self._agents_in_flight.add(agent.id)
        await self.repo.sessions.update_status(session.id, SessionStatus.WORKING, started=True)
        await self.artifact(mid, 'log', 'Sessão iniciada',
                            f'{agent.name} / {agent.provider}\n{prompt}', session.id, session.task_id)
        for message in messages:
            if message.delivery_status == 'pending':
                await self.repo.put(message.model_copy(update={'delivery_status': 'delivered'}))
        await self.notify(mid)
        observed_lines = 0

        async def observe_process(event: ProcessObservation) -> None:
            nonlocal observed_lines
            if event.kind == 'started':
                await self.repo.sessions.set_process(session.id, event.pid, started=True)
                await self.repo.sessions.merge_metadata(session.id, {'process_id': event.pid})
                await self.artifact(mid, 'log', 'Processo CLI iniciado', f'PID {event.pid}', session.id, session.task_id)
                return
            if event.kind != 'stdout' or observed_lines >= 200:
                return
            try:
                data = json.loads(event.line)
            except ValueError:
                return
            if not isinstance(data, dict):
                return
            # Only public lifecycle/tool evidence, never raw reasoning blocks.
            item = data.get('item', {})
            if isinstance(item, dict) and item.get('type') in ('command_execution', 'file_change'):
                observed_lines += 1
                await self.artifact(mid, 'log', 'Atividade do CLI', json.dumps(item), session.id, session.task_id)
            external_id = data.get('thread_id') or (data.get('session_id') if data.get('type') == 'system' else None)
            if isinstance(external_id, str):
                await self.repo.sessions.set_external_session_id(session.id, external_id)
            if data.get('type') == 'assistant':
                message_data = data.get('message', {})
                if isinstance(message_data, dict):
                    for block in message_data.get('content', []):
                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                            observed_lines += 1
                            await self.artifact(mid, 'log', 'Ferramenta do CLI',
                                json.dumps({'name': block.get('name'), 'input': block.get('input')}), session.id, session.task_id)

        token = process_observer.set(observe_process)
        try:
            # Refresh the external id: later turns resume this exact session.
            session = await self.repo.sessions.get_or_raise(session.id)
            workspace = str(session.metadata.get('workspace') or await self.workspace(mission))
            async def run_provider():
                async with self.parallel.acquire(provider=agent.provider,
                                                 project_id=mission.project_id, mission_id=mid,
                                                 binding_id=session.runtime_binding_id):
                    return await self.runtime.execute(session, agent, prompt,
                        workspace=workspace, writable=writable, timeout=self.session_timeout)
            call = asyncio.create_task(run_provider())
            cancel_wait = asyncio.create_task(cancel.wait()) if cancel else None
            try:
                waiting = [call, cancel_wait] if cancel_wait else [call]
                done, _ = await asyncio.wait(waiting, timeout=self.session_timeout, return_when=asyncio.FIRST_COMPLETED)
                if cancel_wait and cancel_wait in done:
                    raise CancelledErrorX('Turno interrompido pelo usuário')
                if call not in done:
                    raise MissionBlocked('Timeout do CLI; turno interrompido.')
                response = call.result()
            finally:
                if not call.done():
                    call.cancel()
                if cancel_wait:
                    cancel_wait.cancel()
                await asyncio.gather(call, *([cancel_wait] if cancel_wait else []), return_exceptions=True)
            await self.artifact(mid, 'log', 'Resposta do CLI', response.content, session.id, session.task_id)
            external = (response.structured_output or {}).get('thread_id') or (response.structured_output or {}).get('session_id')
            if isinstance(external, str) and external:
                await self.repo.sessions.set_external_session_id(session.id, external)
            value = parse_output(self.clean(response.content), model)
            await self.repo.sessions.update_status(session.id, SessionStatus.WAITING)
            await self.notify(mid)
            return value
        except BaseException:
            await self.repo.sessions.update_status(session.id, SessionStatus.INTERRUPTED, finished=True)
            await self.notify(mid)
            raise
        finally:
            self._agents_in_flight.discard(agent.id)
            process_observer.reset(token)
            await self.repo.sessions.merge_metadata(session.id, {'process_id': None})

    async def analyze(self, mid: str) -> None:
        mission = await self.repo.get(Mission, mid)
        await self.status(mid, 'analyzing')
        leader_choice = await self.choose(mission, 'leader')
        leader = await self.new_session(mission, leader_choice)
        agents = await self.ctx.agents_repo.list()
        catalog = []
        for agent in agents:
            if not agent.active:
                continue
            binding = await self.ctx.runtime_bindings_repo.get(agent.runtime_binding_id) if agent.runtime_binding_id else None
            active_count = len([s for s in await self.repo.sessions.list_by_agent(agent.id)
                                if s.status in (SessionStatus.STARTING, SessionStatus.WORKING, SessionStatus.WAITING)])
            catalog.append({'id': agent.id, 'name': agent.name, 'role': agent.role,
                            'capabilities': [c.name for c in agent.capabilities], 'provider': agent.provider,
                            'runtime_binding_id': agent.runtime_binding_id,
                            'active_sessions': active_count, 'max_sessions': agent.max_sessions,
                            'binding_capacity': binding.observed_capacity if binding else None,
                            'binding_reserved': binding.reserved_slots if binding else None,
                            'permissions': agent.permissions.model_dump()})
        extra = '\n'.join(i.content for i in await self.repo.list(Instruction, mid))
        plan = await self.turn(mid, leader,
            f'Analise o repositório e proponha tarefas para: {mission.request}\nInstruções adicionais: {extra}\n'
            f'Catálogo real: {json.dumps(catalog)}\n'
            'Use capacidades do catálogo. Inclua critérios verificáveis e dependências. '
            'Não implemente agora. A implementação e a revisão serão atribuídas pelo backend.', PlanOutput)
        required = sorted({c for t in plan.tasks for c in t.capabilities})
        worker = await self.choose(mission, 'worker', {leader.agent_id}, required)
        reviewer = await self.choose(mission, 'reviewer', {leader.agent_id, worker.agent_id})
        versions = await self.repo.list(MissionPlan, mid)
        saved = MissionPlan(**plan.model_dump(), id=new_id('plan'), mission_id=mid,
            version=len(versions) + 1, leader_session_id=leader.id,
            choices=[leader_choice, worker, reviewer], created_at=utc_now())
        await self.repo.put(saved)
        for instruction in await self.repo.list(Instruction, mid):
            if instruction.disposition in ('pending', 'replan'):
                await self.repo.put(instruction.model_copy(update={'disposition': 'context_share',
                    'reason': f'Incorporada ao plano v{saved.version} pelo líder'}))
        current = await self.repo.get(Mission, mid)
        await self.repo.put(current.model_copy(update={'current_plan_id': saved.id}))
        await self.status(mid, 'planned', 'Plano validado. Revise a equipe e inicie a missão.')

    async def process_instructions(self, mid: str, leader: Session) -> None:
        for instruction in await self.repo.list(Instruction, mid):
            if instruction.disposition != 'pending':
                continue
            decision = await self.turn(mid, leader,
                f'Classifique a nova instrução: {instruction.content}\n'
                'context_share: complementa o escopo. replan: exige mudar tarefas. '
                'queued: pedido independente para depois. Explique a decisão.', InstructionDecision)
            await self.repo.put(instruction.model_copy(update={
                'disposition': decision.disposition, 'reason': decision.reason}))
            await self.message(mid, leader.id, None, 'context_share',
                f'{instruction.content}\nDecisão: {decision.disposition}: {decision.reason}')
            if decision.disposition == 'replan':
                raise MissionBlocked('Líder solicitou replanejamento. Analise novamente incluindo a instrução.')

    async def run(self, mid: str) -> None:
        mission = await self.repo.get(Mission, mid)
        if not mission.current_plan_id:
            raise MissionBlocked('Plano ausente')
        plan = await self.repo.get(MissionPlan, mission.current_plan_id)
        leader = await self.repo.sessions.get_or_raise(plan.leader_session_id)
        await self.status(mid, 'running')
        await self.process_instructions(mid, leader)
        if len(plan.tasks) >= 2 and any(t.isolation == "write" for t in plan.tasks):
            await self.run_parallel(mission, plan, leader)
            return
        snapshot = await self.repo.snapshot(mid)
        existing = {str(t.input.get('plan_key')): t for t in snapshot.tasks
                    if t.input.get('plan_id') == plan.id}
        for planned in plan.tasks:
            if planned.key not in existing:
                task = await self.repo.tasks.create(TaskCreate(project_id=mission.project_id,
                    title=planned.title, description=planned.description,
                    input={'mission_id': mid, 'plan_id': plan.id, 'plan_key': planned.key}))
                await self.repo.link('task', mid, task.id)
                existing[planned.key] = task
        completed = {k for k, t in existing.items() if t.status == TaskStatus.COMPLETED}
        pending = {t.key: t for t in plan.tasks if t.key not in completed}
        while pending:
            ready = sorted(k for k, t in pending.items() if set(t.depends_on) <= completed)
            if not ready:
                raise MissionBlocked('Dependências não resolvidas')
            for key in ready:
                await self.process_instructions(mid, leader)
                await self.work_task(mission, plan, leader, existing[key].id, pending[key].acceptance)
                completed.add(key)
                del pending[key]
        await self.process_instructions(mid, leader)
        await self.status(mid, 'testing')
        await self.validate(mission)
        snapshot = await self.repo.snapshot(mid)
        paths = sorted({p for a in snapshot.artifacts if a.kind == 'diff' for p in a.paths})
        tests = [a for a in snapshot.artifacts if a.kind == 'test']
        result = ('Missão concluída com revisão independente e validação real.\n'
            + '\n'.join(f'- {t.title}: {t.status.value}' for t in snapshot.tasks)
            + '\nArquivos alterados: ' + (', '.join(paths) or 'nenhum detectado')
            + '\nTestes: ' + '; '.join(f'{a.title} (exit {a.exit_code})' for a in tests)
            + '\nLimitações do plano: ' + '; '.join(plan.limitations)
            + '\nExecução serial, sem worktree. Consulte relatórios e logs para limitações dos agentes.')
        await self.artifact(mid, 'report', 'Resultado consolidado', result)
        for session in snapshot.sessions:
            if session.status == SessionStatus.WAITING:
                await self.repo.sessions.update_status(session.id, SessionStatus.COMPLETED, finished=True)
        await self.status(mid, 'completed', result=result)

    async def run_parallel(self, mission: Mission, plan: MissionPlan, leader: Session) -> None:
        """Run independent write tasks in isolated worktrees, then integrate only reviewed commits."""
        mid = mission.id
        workspace = Path(await self.workspace(mission))
        base_sha = await self.worktrees.base_sha(workspace)
        pending = {task.key: task for task in plan.tasks}
        completed: set[str] = set()
        # The scheduler admits every currently-ready task at once; dependencies are
        # still enforced in deterministic waves.
        while pending:
            ready = sorted(k for k, task in pending.items() if set(task.depends_on) <= completed)
            if not ready:
                raise MissionBlocked("Grafo paralelo não possui tarefa pronta; dependência inválida.")
            choices: dict[str, Choice] = {}
            reserved = {leader.agent_id}
            for key in ready:
                choices[key] = await self.choose(mission, 'worker', reserved, pending[key].capabilities)
                reserved.add(choices[key].agent_id)
            reviewer_choice = await self.choose(mission, 'reviewer', reserved)
            outcomes = await asyncio.gather(*(self.run_parallel_task(
                mission, plan, leader, pending[key], workspace, base_sha, choices[key], reviewer_choice)
                for key in ready), return_exceptions=True)
            failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            if failures:
                raise failures[0]
            completed.update(ready)
            for key in ready:
                del pending[key]
        task_snapshot = await self.repo.snapshot(mid)
        task_ids = {str(task.input.get('plan_key')): task.id for task in task_snapshot.tasks}
        forecasts = [value.model_copy(update={
            'task_id': task_ids[value.task_id],
            'other_task_id': task_ids.get(value.other_task_id) if value.other_task_id else None,
        }) for value in forecast(mid, plan.tasks) if value.task_id in task_ids]
        await self.ctx.parallel_repo.replace_forecasts(mid, forecasts)
        await self.integrate_parallel(mission, plan, workspace, base_sha)

    async def run_parallel_task(self, mission: Mission, plan: MissionPlan, leader: Session,
                                planned, project_root: Path, base_sha: str, worker_choice: Choice,
                                reviewer_choice: Choice) -> None:
        mid = mission.id
        task = await self.repo.tasks.create(TaskCreate(
            project_id=mission.project_id, title=planned.title, description=planned.description,
            input={'mission_id': mid, 'plan_id': plan.id, 'plan_key': planned.key,
                   'isolation': planned.isolation, 'expected_paths': planned.expected_paths,
                   'validation_commands': planned.validation_commands}))
        await self.repo.link('task', mid, task.id)
        selected_agent = await self.ctx.agents_repo.get(worker_choice.agent_id)
        binding = await self.ctx.runtime_bindings_repo.get(selected_agent.runtime_binding_id) if selected_agent and selected_agent.runtime_binding_id else None
        lease = ConcurrencyLease(
            id=new_id('lease'), mission_id=mid, task_id=task.id, project_id=mission.project_id,
            provider=selected_agent.provider if selected_agent else 'unknown',
            runtime_binding_id=binding.id if binding else None,
            expires_at=utc_now() + timedelta(minutes=30), created_at=utc_now())
        admitted = await self.ctx.parallel_repo.acquire(lease, limits={
            'global': self.parallel.limits.global_sessions,
            'provider': self.parallel.limits.per_provider,
            'runtime_binding': min(self.parallel.limits.per_binding, binding.observed_capacity if binding else self.parallel.limits.per_binding),
            'project': self.parallel.limits.per_project,
            'mission': self.parallel.limits.per_mission,
        })
        if not admitted:
            raise MissionBlocked(f'Limite de concorrência atingido para a task {planned.key}.')
        worker = await self.new_session(mission, worker_choice, task.id)
        branch = f"agentmash/mission-{mid}/task-{task.id}"
        wt = await self.worktrees.create(mission=mission, task_id=task.id, project_root=project_root,
                                          base_sha=base_sha, branch_name=branch)
        await self.ctx.parallel_repo.update_worktree(wt.id, session_id=worker.id)
        await self.repo.sessions.assign_worktree(worker.id, wt.id)
        await self.repo.sessions.merge_metadata(worker.id, {'workspace': wt.path, 'isolation': 'worktree',
                                                             'worktree_id': wt.id, 'base_sha': base_sha,
                                                             'branch': branch})
        await self.repo.tasks.update_status(task.id, TaskStatus.RUNNING)
        await self.message(mid, leader.id, worker.id, 'handoff',
            f"Implementação isolada na branch {branch}. {planned.description}\nCritérios: {planned.acceptance}", task.id)
        baseline = await asyncio.to_thread(snapshot_files, wt.path)
        await self.artifact(mid, 'decision', 'Baseline da tarefa',
                            f'Base SHA: {base_sha}; branch: {branch}', worker.id, task.id, files=baseline)
        for round_number in range(1, self.max_review_rounds + 1):
            output = await self.turn(mission.id, worker, (
                f"Implemente na sua worktree isolada: {planned.description}\n"
                f"Critérios: {planned.acceptance}\nNão altere a main nem outra worktree. "
                "Descreva os arquivos e testes no JSON."), WorkerOutput, writable=planned.isolation == 'write')
            if output.human_input_required:
                raise HumanInputRequired(output.human_input_required)
            head_sha = await self.worktrees.commit(wt, f"AgentMash: {planned.title}")
            wt = wt.model_copy(update={'head_sha': head_sha})
            await self.artifact(mid, 'report', 'Entrega isolada', output.summary, worker.id, task.id,
                                paths=output.files)
            diff = await self.capture_diff_at(mission, task.id, worker.id, wt.path, baseline)
            reviewer = await self.new_session(mission, reviewer_choice, task.id, workspace=wt.path, isolation='review')
            async with self.review_gate:
                review = await self.turn(mission.id, reviewer,
                    f"Revise independentemente a task {planned.title}. Base SHA {base_sha}; head SHA {head_sha}. "
                    f"Critérios: {planned.acceptance}. Diff/evidência:\n{diff.content}\n"
                    "Se houver qualquer falha corrigível, use changes_requested com finding concreto. "
                    "Use human_input_required somente se faltar uma decisão, credencial ou permissão externa. "
                    f"O backend já registrou a main no projeto {project_root} e o base SHA {base_sha}; não solicite ao usuário acesso à main "
                    "nem evidência adicional sobre arquivos fora da sua worktree de revisão.", ReviewOutput)
            review_row = Review(**review.model_dump(), id=new_id('review'), mission_id=mid,
                task_id=task.id, worker_session_id=worker.id, reviewer_session_id=reviewer.id,
                round=round_number, created_at=utc_now())
            await self.repo.put(review_row)
            await self.message(mid, reviewer.id, worker.id, review.verdict, review.justification, task.id)
            if review.verdict == 'approval':
                await self.repo.tasks.update_status(task.id, TaskStatus.COMPLETED,
                    result={'review_id': review_row.id, 'head_sha': head_sha},
                    completed_at=utc_now().isoformat())
                await self.repo.sessions.update_status(worker.id, SessionStatus.COMPLETED, finished=True)
                await self.repo.sessions.update_status(reviewer.id, SessionStatus.COMPLETED, finished=True)
                await self.ctx.parallel_repo.update_worktree(wt.id, status='active', head_sha=head_sha)
                return
            if review.verdict == 'human_input_required':
                raise HumanInputRequired(review.justification)
            await self.repo.tasks.update_status(task.id, TaskStatus.WAITING)
        raise MissionBlocked(f"Limite de revisões atingido para {planned.key}.")

    async def capture_diff_at(self, mission: Mission, task_id: str, session_id: str,
                              path: str, baseline) -> Artifact:
        git = GitTool(path)
        status, diff = await asyncio.gather(git.status(), git.diff())
        after = await asyncio.to_thread(snapshot_files, path)
        evidence, paths = describe_changes(baseline, after)
        return await self.artifact(mission.id, 'diff', 'Diff isolado',
            evidence + "\n" + status.stdout + "\n" + diff.stdout, session_id, task_id, paths)

    async def integrate_parallel(self, mission: Mission, plan: MissionPlan,
                                 project_root: Path, base_sha: str) -> None:
        mid = mission.id
        integration_branch = f"agentmash/mission-{mid}/integration"
        integration_root = self.worktrees.root_for(project_root) / "integration"
        if integration_root.exists():
            raise MissionBlocked("Worktree de integração existente requer recuperação humana.")
        integration_root.parent.mkdir(parents=True, exist_ok=True)
        created = await self.worktrees.git(project_root, ["worktree", "add", "-b", integration_branch,
                                                            str(integration_root), base_sha])
        if not created.success:
            raise MissionBlocked("Não foi possível criar a worktree de integração: " + created.stderr[:800])
        try:
            snapshot = await self.repo.snapshot(mid)
            tasks = sorted(snapshot.tasks, key=lambda t: str(t.input.get('plan_key', t.id)))
            for task in tasks:
                wt = await self.ctx.parallel_repo.worktree_for_task(mid, task.id)
                if wt is None or task.status != TaskStatus.COMPLETED:
                    raise MissionBlocked("Só tasks aprovadas podem ser integradas.")
                ok, commit_sha, error = await self.worktrees.integrate(
                    worktree=wt, integration_root=integration_root, integration_branch=integration_branch)
                await self.ctx.parallel_repo.add_integration(IntegrationAttempt(
                    id=new_id('integration'), mission_id=mid, task_id=task.id,
                    integration_branch=integration_branch, source_branch=wt.branch_name,
                    base_sha=base_sha, result='integrated' if ok else 'conflict',
                    commit_sha=commit_sha or None, message=error, created_at=utc_now()))
                if not ok:
                    await self._record_integration_conflict(mission, integration_root, wt, base_sha, error)
                    await self.status(mid, 'blocked', 'Conflito de integração requer agente integrador/humano: ' + error)
                    return
            gate = await self.run_quality_gate(mission, integration_root, None, 'post-integration tests')
            if not gate.passed:
                await self.status(mid, 'blocked', 'Quality gate pós-integração falhou.')
                return
            result = (f"Integration branch: {integration_branch}\nBase SHA: {base_sha}\n"
                      f"Worktrees aprovadas: {len(tasks)}\nQuality gate: {gate.name} exit {gate.exit_code}\n"
                      "A main permaneceu intocada. Aguardando aprovação humana antes de qualquer integração manual.")
            await self.artifact(mid, 'report', 'IntegrationResult', result)
            await self.status(mid, 'awaiting_human_approval', result=result)
        finally:
            # Keep the integration worktree for inspection; cleanup is explicit and safe.
            pass

    async def _record_integration_conflict(self, mission: Mission, integration_root: Path,
                                           source: object, base_sha: str, message: str) -> None:
        """Persist conflict metadata after the safe merge operation is aborted."""
        branch = getattr(source, 'branch_name', '')
        head = getattr(source, 'head_sha', None) or base_sha
        status = await self.worktrees.git(integration_root, ['status', '--porcelain=v1'])
        paths = [line[3:].strip().strip('"') for line in status.stdout.splitlines() if len(line) > 3]
        for line in message.splitlines():
            match = re.search(r'CONFLICT .* in (.+)$', line)
            if match:
                paths.append(match.group(1).strip())
        now = utc_now()
        conflict_id = new_id('conflict')
        files = [ConflictFile(id=new_id('conflict_file'), conflict_id=conflict_id, path=path,
                              classification=classify_conflict(path), created_at=now)
                 for path in sorted(set(paths))]
        value = IntegrationConflict(id=conflict_id, mission_id=mission.id, status='detected',
            classification=files[0].classification if files else 'unknown', base_sha=base_sha,
            ours_sha=base_sha, theirs_sha=head, integration_head=base_sha,
            data={'message': self.clean(message), 'source_branch': branch,
                  'integration_branch': f'agentmash/mission-{mission.id}/integration'}, files=files,
            created_at=now, updated_at=now)
        await self.ctx.integration_repo.add_conflict(value)

    async def assist_conflict(self, mission_id: str, conflict_id: str,
                              integrator_agent_id: str, reviewer_agent_id: str) -> dict[str, object]:
        """Run one real, bounded integrator -> reviewer resolution attempt.

        The integration worktree is separate from the user's checkout. The
        method is idempotent for an already proposed/approved attempt and
        leaves the branch untouched until :meth:`approve_conflict` is called.
        """
        mission = await self.repo.get(Mission, mission_id)
        conflicts = await self.ctx.integration_repo.list_conflicts(mission_id)
        conflict = next((item for item in conflicts if item.id == conflict_id), None)
        if conflict is None:
            raise ValidationError('Conflito de integração inexistente.')
        previous = await self.ctx.integration_repo.attempts(conflict_id)
        if previous and previous[-1].status in {'resolution_proposed', 'reviewing', 'awaiting_human_approval', 'resolved'}:
            return previous[-1].model_dump(mode='json')
        if integrator_agent_id == reviewer_agent_id:
            raise ValidationError('O integrador e o reviewer precisam ser Agents diferentes.')
        workspace = await self.workspace(mission)
        project_root = await asyncio.to_thread(lambda: Path(workspace).resolve())
        root = self.worktrees.root_for(project_root)
        attempt_no = len(previous) + 1
        resolution_path = (root / f'resolution-{conflict.id}-{attempt_no}').resolve()
        if not resolution_path.is_relative_to(root.resolve()):
            raise ValidationError('Worktree de resolução fora da raiz controlada.')
        branch = f'agentmash/mission-{mission.id}/resolution-{attempt_no}'
        integration_branch = str(conflict.data.get('integration_branch', f'agentmash/mission-{mission.id}/integration'))
        source_branch = str(conflict.data.get('source_branch', ''))
        root.mkdir(parents=True, exist_ok=True)
        if not resolution_path.exists():
            created = await self.worktrees.git(project_root, ['worktree', 'add', '-b', branch, str(resolution_path), integration_branch])
            if not created.success:
                raise MissionBlocked('Não foi possível criar a worktree de resolução: ' + created.stderr[:800])
        merge = await self.worktrees.git(resolution_path, ['merge', '--no-edit', '--no-commit', source_branch])
        if merge.success:
            raise MissionBlocked('O conflito não se reproduziu na worktree de resolução; nenhuma resolução foi fabricada.')
        now = utc_now()
        stage_context: dict[str, dict[str, str]] = {}
        for file in conflict.files:
            stages: dict[str, str] = {}
            for label, ref in (('base', ':1:'), ('ours', ':2:'), ('theirs', ':3:')):
                staged = await self.worktrees.git(resolution_path, ['show', f'{ref}{file.path}'])
                if staged.success:
                    stages[label] = self.clean(staged.stdout[:100000])
            stage_context[file.path] = stages
        integrator = await self.new_session(mission, Choice(agent_id=integrator_agent_id, role='integrator', reason='Agente integrador independente dos autores'), workspace=str(resolution_path), isolation='resolution')
        attempt = ResolutionAttempt(id=new_id('resolution'), conflict_id=conflict_id, attempt_no=attempt_no,
            status='analyzing', integrator_session_id=integrator.id, strategy='', data={'base_sha': conflict.base_sha, 'ours_sha': conflict.ours_sha, 'theirs_sha': conflict.theirs_sha, 'stages': stage_context}, created_at=now, updated_at=now, resolution_path=str(resolution_path), resolution_branch=branch)
        await self.ctx.integration_repo.add_attempt(attempt)
        await self.ctx.integration_repo.update_conflict(conflict_id, status='analyzing', integrator_session_id=integrator.id)
        snapshot = await self.repo.snapshot(mission_id)
        workers = [a for a in snapshot.assignments if a.role == 'worker' and a.active]
        prompt = (f'Você é o integrador independente. Resolva o conflito nesta worktree, editando os arquivos e preservando os dois comportamentos.\n'
                  f'Pedido: {mission.request}\nBase: {conflict.base_sha}\nOurs: {conflict.ours_sha}\nTheirs: {conflict.theirs_sha}\n'
                  f'Arquivos: {[f.path for f in conflict.files]}\nForecast: {conflict.data}\n'
                  'Inspecione stages base/ours/theirs, não descarte silenciosamente nenhum lado. Se precisar de contexto, registre uma pergunta curta no campo question. Depois execute testes direcionados e retorne estratégia, decisões por arquivo, riscos e testes.')
        proposal = await self.turn(mission_id, integrator, prompt, IntegrationProposal, writable=True)
        question_text = proposal.question or ('Confirme a intenção preservada no contrato e qualquer comportamento que não possa ser removido.')
        if workers:
            await self.ctx.integration_repo.update_conflict(conflict_id, status='awaiting_context')
            for assignment in workers[:2]:
                worker = await self.repo.sessions.get_or_raise(assignment.session_id)
                question = await self.message(mission_id, integrator.id, worker.id, 'question', question_text, assignment.task_id)
                answer = await self.turn(mission_id, worker, f'Responda ao integrador sobre esta pergunta, sem editar arquivos: {question_text}', WorkerOutput)
                await self.message(mission_id, worker.id, integrator.id, 'answer', answer.summary, assignment.task_id, reply_to=question.id)
        await self.ctx.integration_repo.update_conflict(conflict_id, status='resolution_proposed')
        add = await self.worktrees.git(resolution_path, ['add', '--', '.'])
        if not add.success:
            raise MissionBlocked('Integrador não deixou uma resolução aplicável: ' + add.stderr[:800])
        commit = await self.worktrees.git(resolution_path, ['commit', '-m', f'Resolve integration conflict {conflict_id}'])
        if not commit.success:
            raise MissionBlocked('Não foi possível registrar a proposta do integrador: ' + commit.stderr[:800])
        head = await self.worktrees.git(resolution_path, ['rev-parse', 'HEAD'])
        await self.ctx.integration_repo.update_conflict(conflict_id, status='reviewing', reviewer_session_id=None)
        await self.ctx.integration_repo.update_attempt(attempt.id, status='reviewing', commit_sha=head.stdout.strip(), strategy=proposal.strategy, data=proposal.model_dump(mode='json'))
        reviewer = await self.new_session(mission, Choice(agent_id=reviewer_agent_id, role='reviewer', reason='Reviewer independente do integrador'), workspace=str(resolution_path), isolation='resolution-review')
        await self.ctx.integration_repo.update_conflict(conflict_id, status='reviewing', reviewer_session_id=reviewer.id)
        review = await self.turn(mission_id, reviewer, f'Revise a resolução commit {head.stdout.strip()} em modo somente leitura. Verifique preservação das duas tarefas, segurança, contratos e testes. Diff: {proposal.model_dump_json()}', ReviewOutput)
        verdict = 'approved' if review.verdict == 'approval' else review.verdict
        await self.ctx.integration_repo.add_review(ResolutionReview(id=new_id('resolution_review'), conflict_id=conflict_id, attempt_id=attempt.id, reviewer_session_id=reviewer.id, verdict=verdict, findings=[{'severity': 'high' if verdict != 'approved' else 'info', 'explanation': review.justification, 'action': '; '.join(review.challenges)}], created_at=utc_now()))
        if verdict != 'approved':
            await self.ctx.integration_repo.update_conflict(conflict_id, status='changes_requested')
            return {'conflict_id': conflict_id, 'status': 'changes_requested', 'review': review.model_dump(mode='json')}
        gate = await self.run_quality_gate(mission, resolution_path, None, 'resolution quality gates')
        if not gate.passed:
            await self.ctx.integration_repo.update_conflict(conflict_id, status='blocked')
            return {'conflict_id': conflict_id, 'status': 'blocked', 'gate': gate.model_dump(mode='json')}
        await self.ctx.integration_repo.update_conflict(conflict_id, status='awaiting_human_approval')
        return {'conflict_id': conflict_id, 'status': 'awaiting_human_approval', 'attempt_id': attempt.id, 'integrator_session_id': integrator.id, 'reviewer_session_id': reviewer.id, 'commit_sha': head.stdout.strip(), 'resolution_branch': branch}

    async def approve_conflict(self, conflict_id: str, rationale: str) -> None:
        row = await self.ctx.db.fetch_one('SELECT mission_id FROM integration_conflicts WHERE id=?', (conflict_id,))
        if row is None:
            raise ValidationError('Conflito inexistente.')
        conflicts = await self.ctx.integration_repo.list_conflicts(row['mission_id'])
        conflict = next((item for item in conflicts if item.id == conflict_id), None)
        if conflict is None:
            raise ValidationError('Conflito inexistente.')
        attempts = await self.ctx.integration_repo.attempts(conflict_id)
        if not attempts or not attempts[-1].commit_sha or not attempts[-1].resolution_branch:
            raise ValidationError('Não há resolução revisada aguardando aprovação.')
        mission = await self.repo.get(Mission, conflict.mission_id)
        workspace = await self.workspace(mission)
        root = await asyncio.to_thread(lambda: Path(workspace).resolve())
        integration = self.worktrees.root_for(root) / 'integration'
        merged = await self.worktrees.git(integration, ['merge', '--ff-only', attempts[-1].resolution_branch])
        if not merged.success:
            raise MissionBlocked('A integration branch mudou; revalide a resolução antes de aplicar.')
        await self.ctx.integration_repo.add_decision(ResolutionDecision(id=new_id('resolution_decision'), conflict_id=conflict_id, attempt_id=attempts[-1].id, decision='approved', rationale=self.clean(rationale), created_at=utc_now()))
        await self.ctx.integration_repo.update_conflict(conflict_id, status='resolved')

    async def run_quality_gate(self, mission: Mission, root: Path, task_id: str | None,
                               name: str) -> QualityGateRun:
        profiles = await self.ctx.integration_repo.list_profiles(mission.project_id)
        profile = next((item for item in profiles if item.is_default), None)
        if profile:
            last: QualityGateRun | None = None
            for definition in sorted((gate for gate in profile.gates if gate.enabled), key=lambda gate: gate.order):
                validate_gate(definition, root)
                started = asyncio.get_running_loop().time()
                result = await get_runner().run(definition.argv, cwd=root / definition.cwd,
                                                timeout=definition.timeout_seconds,
                                                cancel_event=self.cancel_events.get(mission.id))
                last = QualityGateRun(id=new_id('gate'), mission_id=mission.id, task_id=task_id,
                    name=f'{profile.name}: {definition.name}', command=definition.argv, exit_code=result.returncode,
                    duration_ms=int((asyncio.get_running_loop().time() - started) * 1000),
                    summary=self.clean((result.stdout + '\n' + result.stderr)[:definition.log_limit]),
                    passed=result.success, created_at=utc_now())
                await self.ctx.parallel_repo.add_gate(last)
                await self.artifact(mission.id, 'test', last.name, last.summary, command=last.command, exit_code=last.exit_code)
                if definition.required and not last.passed:
                    return last
            if last is not None:
                return last
        planner = CommandPlanner(root)
        command = planner.resolve(ProjectAction.RUN_TESTS)
        if command is None:
            raise MissionBlocked('Nenhum comando de testes reconhecido na integração.')
        started = asyncio.get_running_loop().time()
        result = await get_runner().run(command, cwd=root, timeout=self.session_timeout,
                                         cancel_event=self.cancel_events.get(mission.id))
        gate = QualityGateRun(id=new_id('gate'), mission_id=mission.id, task_id=task_id,
            name=name, command=command, exit_code=result.returncode,
            duration_ms=int((asyncio.get_running_loop().time() - started) * 1000),
            summary=self.clean((result.stdout + '\n' + result.stderr)[:10000]),
            passed=result.success, created_at=utc_now())
        await self.ctx.parallel_repo.add_gate(gate)
        await self.artifact(mission.id, 'test', name, gate.summary, command=command, exit_code=gate.exit_code)
        return gate

    async def work_task(self, mission: Mission, plan: MissionPlan, leader: Session,
                        task_id: str, acceptance: list[str]) -> None:
        mid = mission.id
        task = await self.repo.tasks.get_or_raise(task_id)
        assignments = await self.repo.list(Assignment, mid)
        worker_assignment = next((a for a in reversed(assignments)
                                  if a.task_id == task_id and a.role == 'worker' and a.active), None)
        worker_choice = next(c for c in plan.choices if c.role == 'worker')
        reviewer_choice = next(c for c in plan.choices if c.role == 'reviewer')
        worker = (await self.repo.sessions.get_or_raise(worker_assignment.session_id)
                  if worker_assignment else await self.new_session(mission, worker_choice, task_id))
        if worker.agent_id == reviewer_choice.agent_id:
            raise MissionBlocked('Autoaprovação proibida')
        reviewer = await self.new_session(mission, reviewer_choice, task_id)
        await self.repo.tasks.update_status(task_id, TaskStatus.RUNNING)
        await self.message(mid, leader.id, worker.id, 'handoff',
            task.description + '\nCritérios: ' + '; '.join(acceptance), task_id)
        baselines = [a for a in await self.repo.list(Artifact, mid)
                     if a.task_id == task_id and a.title == 'Baseline da tarefa']
        if not baselines:
            files = await asyncio.to_thread(snapshot_files, await self.workspace(mission))
            await self.artifact(mid, 'decision', 'Baseline da tarefa',
                'Hashes e conteúdo limitado capturados antes da escrita; ignora dependências, builds e segredos.',
                task_id=task_id, files=files)
        last: str | None = None
        for round_number in range(1, self.max_review_rounds + 1):
            await self.status(mid, 'running' if round_number == 1 else 'changes_requested')
            output = await self.turn(mid, worker,
                f'Implemente/corrija: {task.description}\nCritérios: {acceptance}\n'
                'Considere todas as mensagens recebidas. Se precisar de contexto, use question; '
                'se depender de permissão humana, use human_input_required.', WorkerOutput, writable=True)
            if output.human_input_required:
                await self.message(mid, worker.id, None, 'human_input_required', output.human_input_required, task_id)
                raise HumanInputRequired(output.human_input_required)
            if output.question:
                question = await self.message(mid, worker.id, leader.id, 'question', output.question, task_id)
                answer = await self.turn(mid, leader,
                    'Responda à pergunta recebida com contexto verificável. Use summary para a resposta.', WorkerOutput)
                await self.message(mid, leader.id, worker.id, 'answer', answer.summary, task_id, question.id)
                output = await self.turn(mid, worker, 'Continue a implementação com a resposta recebida.',
                                         WorkerOutput, writable=True)
                if output.question or output.human_input_required:
                    raise MissionBlocked(output.human_input_required or output.question or 'Contexto insuficiente')
            report = await self.artifact(mid, 'report', 'Entrega do trabalhador',
                output.summary + '\nLimitações: ' + '; '.join(output.limitations), worker.id, task_id)
            diff = await self.capture_diff(mission, worker.id, task_id)
            handoff = await self.message(mid, worker.id, reviewer.id,
                'fix_response' if round_number > 1 else 'handoff', output.summary,
                task_id, last, [report.id, diff.id])
            await self.message(mid, worker.id, reviewer.id, 'review_request',
                'Revise criticamente o código e os critérios; questione problemas concretos.', task_id,
                handoff.id, [diff.id])
            await self.status(mid, 'reviewing')
            await self.repo.tasks.update_status(task_id, TaskStatus.REVIEWING)
            review_output = await self.turn(mid, reviewer,
                f'Revise independentemente {task.description}. Critérios: {acceptance}. '
                f'Inspecione arquivos e diff reais. Diff capturado:\n{diff.content}\n'
                'approval exige todos os critérios; changes_requested deve explicar correções.', ReviewOutput)
            review = Review(**review_output.model_dump(), id=new_id('review'), mission_id=mid,
                task_id=task_id, worker_session_id=worker.id, reviewer_session_id=reviewer.id,
                round=round_number, created_at=utc_now())
            await self.repo.put(review)
            for challenge in review.challenges:
                await self.message(mid, reviewer.id, worker.id, 'review_challenge', challenge, task_id)
            message = await self.message(mid, reviewer.id, worker.id, review.verdict,
                review.justification, task_id, handoff.id)
            last = message.id
            if review.verdict == 'approval':
                await self.repo.tasks.update_status(task_id, TaskStatus.COMPLETED,
                    result={'summary': output.summary, 'review_id': review.id},
                    completed_at=utc_now().isoformat())
                await self.repo.sessions.update_status(worker.id, SessionStatus.COMPLETED, finished=True)
                await self.repo.sessions.update_status(reviewer.id, SessionStatus.COMPLETED, finished=True)
                await self.notify(mid)
                return
            if review.verdict == 'human_input_required':
                raise HumanInputRequired(review.justification)
            await self.repo.tasks.update_status(task_id, TaskStatus.WAITING)
            await self.process_instructions(mid, leader)
        raise MissionBlocked('Limite de ciclos de correção atingido. Revisão ainda solicita mudanças.')

    async def capture_diff(self, mission: Mission, session_id: str, task_id: str) -> Artifact:
        git = GitTool(await self.workspace(mission))
        status, diff, staged = await asyncio.gather(git.status(), git.diff(), git.diff(staged=True))
        if not status.success or not diff.success or not staged.success:
            raise MissionBlocked('Git/diff indisponível; não é possível auditar os arquivos alterados.')
        baselines = [a for a in await self.repo.list(Artifact, mission.id)
                     if a.task_id == task_id and a.title == 'Baseline da tarefa']
        if not baselines:
            raise MissionBlocked('Baseline ausente; não é possível atribuir alterações à tarefa.')
        after = await asyncio.to_thread(snapshot_files, await self.workspace(mission))
        evidence, paths = describe_changes(baselines[0].files, after)
        return await self.artifact(mission.id, 'diff', 'Alterações atuais do repositório',
            evidence + '\nEstado Git (pode incluir alterações pré-existentes):\n' + status.stdout + '\n' + diff.stdout + '\n' + staged.stdout, session_id, task_id, paths)

    async def validate(self, mission: Mission) -> None:
        workspace = await self.workspace(mission)
        planner = CommandPlanner(workspace)
        argv = planner.resolve(ProjectAction.RUN_TESTS)
        if argv is None:
            raise MissionBlocked('Nenhum comando de testes reconhecido no projeto. Configure testes e retome.')
        result = await get_runner().run(argv, cwd=Path(workspace), timeout=self.session_timeout,
                                       cancel_event=self.cancel_events.get(mission.id))
        await self.artifact(mission.id, 'test', ' '.join(argv), result.stdout + '\n' + result.stderr,
                            command=argv, exit_code=result.returncode)
        if not result.success:
            raise MissionBlocked(f'Validação falhou (exit {result.returncode}); consulte o artefato de testes.')

    async def stop(self, mid: str, *, pause: bool, session_id: str | None = None) -> None:
        event = self.cancel_events.get(mid)
        if event:
            event.set()
        snapshot = await self.repo.snapshot(mid)
        for session in snapshot.sessions:
            if session.status == SessionStatus.WORKING:
                agent = await self.ctx.agents_repo.get(session.agent_id)
                if agent:
                    await self.runtime.cancel(session, agent)
        # Cooperative cancellation terminates processes first. Never free a lease early.
        job = self.jobs.get(mid)
        if job:
            await job
        for session in (await self.repo.snapshot(mid)).sessions:
            if session.status not in (SessionStatus.COMPLETED, SessionStatus.CANCELLED):
                await self.repo.sessions.update_status(session.id,
                    SessionStatus.PAUSED if pause else SessionStatus.CANCELLED, finished=not pause)
        for task in snapshot.tasks:
            if task.status != TaskStatus.COMPLETED:
                await self.repo.tasks.update_status(task.id, TaskStatus.WAITING if pause else TaskStatus.CANCELLED)
        await self.status(mid, 'blocked' if pause else 'cancelled',
            'Pausada com interrupção do turno; retomar repassa o contexto persistido.' if pause
            else 'Cancelada pelo usuário; alterações locais preservadas.')

    async def recover(self) -> None:
        for mission in await self.repo.missions():
            if mission.status in ACTIVE:
                snapshot = await self.repo.snapshot(mission.id)
                for worktree in await self.ctx.parallel_repo.list_worktrees(mission.id):
                    state = await self.worktrees.inspect(worktree)
                    if not state['exists']:
                        await self.ctx.parallel_repo.update_worktree(
                            worktree.id, status='orphaned', last_error='Diretório da worktree não existe após restart.')
                for session in snapshot.sessions:
                    if session.status in (SessionStatus.STARTING, SessionStatus.WORKING, SessionStatus.WAITING):
                        await self.repo.sessions.update_status(session.id, SessionStatus.INTERRUPTED, finished=True)
                for task in snapshot.tasks:
                    if task.status in (TaskStatus.RUNNING, TaskStatus.REVIEWING):
                        await self.repo.tasks.update_status(task.id, TaskStatus.WAITING)
                await self.status(mission.id, 'blocked',
                    'Aplicação reiniciada durante execução. Logs preservados; revise o diff e retome explicitamente.')
            await self.repo.release(mission.id)
            await self.ctx.parallel_repo.release(mission_id=mission.id)

    async def close(self) -> None:
        for mid in list(self.jobs):
            await self.stop(mid, pause=True)
