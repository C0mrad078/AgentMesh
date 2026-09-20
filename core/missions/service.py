"""Collaborative mission coordinator. Reuses repositories, CLI adapters and tools.

One supervised coroutine per mission. Agents produce plans and review decisions;
the backend enforces eligibility, dependencies, independence and bounded repairs.
No successful state can be manufactured by a frontend command.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from core.database.repositories.missions_repo import MissionsRepository
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
        elif cmd.action in ('start', 'resume', 'approve'):
            if not mission.current_plan_id:
                raise ValidationError('Analise o pedido antes de iniciar')
            if mission.status not in ('planned', 'awaiting_approval', 'blocked'):
                raise ValidationError('Missão não pode iniciar neste estado')
            if mission.status == 'awaiting_approval' and cmd.action != 'approve':
                raise ValidationError('Registre uma decisão humana explícita antes de retomar.')
            if cmd.action == 'approve' and not cmd.content.strip():
                raise ValidationError('Explique a decisão humana antes de retomar')
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

    async def new_session(self, mission: Mission, choice: Choice, task_id: str | None = None) -> Session:
        agent = await self.ctx.agents_repo.get(choice.agent_id)
        if agent is None:
            raise MissionBlocked('Agente removido')
        provider = await self.ctx.providers_repo.get_by_name(PROVIDER_IDS[agent.provider])
        if provider is None:
            raise MissionBlocked('Provider ausente no catálogo')
        session = await self.repo.sessions.create(SessionCreate(
            agent_id=agent.id, project_id=mission.project_id, provider_id=provider.id,
            backend_type=ExecutionBackendType.SUBSCRIPTION, task_id=task_id,
            metadata={'schema_version': 1, 'mission_id': mission.id, 'role': choice.role,
                      'workspace': await self.workspace(mission)}))
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
            call = asyncio.create_task(self.runtime.execute(session, agent, prompt,
                workspace=await self.workspace(mission), writable=writable, timeout=self.session_timeout))
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
        catalog = [{'id': a.id, 'role': a.role, 'capabilities': [c.name for c in a.capabilities],
                    'provider': a.provider} for a in agents if a.active]
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
                for session in snapshot.sessions:
                    if session.status in (SessionStatus.STARTING, SessionStatus.WORKING, SessionStatus.WAITING):
                        await self.repo.sessions.update_status(session.id, SessionStatus.INTERRUPTED, finished=True)
                for task in snapshot.tasks:
                    if task.status in (TaskStatus.RUNNING, TaskStatus.REVIEWING):
                        await self.repo.tasks.update_status(task.id, TaskStatus.WAITING)
                await self.status(mission.id, 'blocked',
                    'Aplicação reiniciada durante execução. Logs preservados; revise o diff e retome explicitamente.')
            await self.repo.release(mission.id)

    async def close(self) -> None:
        for mid in list(self.jobs):
            await self.stop(mid, pause=True)
