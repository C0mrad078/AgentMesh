"""Execution Engine: drives one task through the full autonomous pipeline.

    Intent Analyzer -> Planner -> Router -> Executor (DAG, parallel where
    possible) -> Verifier -> [Correction loop, bounded] -> Result Aggregator

Every phase is persisted as an `execution_steps` row and streamed to the
bridge via the phase `EventSink` as it transitions, so the desktop UI can
render the step-by-step progress board in real time. Fine-grained internal
events (agent selected, provider call started/completed, tool call, retry,
verification) go through the separate `core.orchestrator.event_bus.EventBus`
-- see `core/bridge/context.py` for how both are wired to persistence and
to the frontend's debug view.

Cancellation is cooperative and real: `request_cancel()` sets an
`asyncio.Event` that is checked between phases, between DAG layers, and
inside `StepExecutor`, which actually cancels the in-flight provider call.

On any unexpected internal exception the engine still deterministically
marks the execution and task `failed` with a safe, generic message -- it
never leaves either stuck in `running` and never lets a raw traceback reach
the frontend. If no AI provider is configured at all, this is treated the
same way with a specific, actionable message (Offline Mode).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from core.agents.models import Agent
from core.agents.prompt_registry import PromptRegistry
from core.agents.registry import AgentRegistry
from core.database.repositories.execution_steps_repo import ExecutionStepsRepository
from core.database.repositories.executions_repo import ExecutionRecord, ExecutionsRepository
from core.orchestrator.aggregator import ResultAggregator
from core.orchestrator.budget import BudgetManager
from core.orchestrator.context_builder import ContextBuilder
from core.orchestrator.dag import build_execution_layers
from core.orchestrator.event_bus import EventBus, EventType, OrchestrationEvent
from core.orchestrator.events import EventSink, ExecutionEvent, noop_sink
from core.orchestrator.executor import StepExecutor
from core.orchestrator.intent_analyzer import IntentAnalyzer
from core.orchestrator.judge import Judge
from core.orchestrator.models import (
    PHASE_LABELS,
    ExecutionPhase,
    ExecutionPlan,
    ExecutionStatus,
    Intent,
    PlanStep,
    RiskLevel,
    RoutingDecision,
    StepResult,
    StepStatus,
)
from core.orchestrator.planner import Planner
from core.orchestrator.router import Router
from core.orchestrator.verifier import Verifier
from core.projects.service import ProjectService
from core.providers.pool import ProviderPool
from core.tasks.models import TERMINAL_TASK_STATUSES, Task, TaskStatus
from core.tasks.service import TaskService
from core.tools.tool_schemas import ToolExecutor
from core.utils.errors import NotFoundError, OrchestratorError, ProviderUnavailableError
from core.utils.ids import new_id
from core.utils.logging import get_logger, log_event

logger = get_logger("orchestrator.engine")

_NO_PROVIDER_MESSAGE = (
    "Nenhum provider de IA configurado. Configure ao menos uma chave de API "
    "em Configurações > Providers para executar tarefas automaticamente."
)


class ExecutionEngine:
    def __init__(
        self,
        executions_repo: ExecutionsRepository,
        steps_repo: ExecutionStepsRepository,
        task_service: TaskService,
        project_service: ProjectService,
        agent_registry: AgentRegistry,
        prompt_registry: PromptRegistry,
        provider_pool: ProviderPool,
        planner: Planner,
        router: Router,
        step_executor: StepExecutor,
        judge: Judge,
        verifier: Verifier,
        aggregator: ResultAggregator,
        context_builder: ContextBuilder,
        budget: BudgetManager,
        event_bus: EventBus,
        *,
        phase_event_sink: EventSink = noop_sink,
        max_review_iterations: int = 3,
    ) -> None:
        self._executions_repo = executions_repo
        self._steps_repo = steps_repo
        self._task_service = task_service
        self._project_service = project_service
        self._agents = agent_registry
        self._prompts = prompt_registry
        self._provider_pool = provider_pool
        self._intent_analyzer = IntentAnalyzer()
        self._planner = planner
        self._router = router
        self._step_executor = step_executor
        self._judge = judge
        self._verifier = verifier
        self._aggregator = aggregator
        self._context_builder = context_builder
        self._budget = budget
        self._events = event_bus
        self._phase_sink = phase_event_sink
        self.max_review_iterations = max_review_iterations
        self._cancel_events: dict[str, asyncio.Event] = {}

    def request_cancel(self, execution_id: str) -> bool:
        event = self._cancel_events.get(execution_id)
        if event is None:
            return False
        event.set()
        return True

    def is_tracked(self, execution_id: str) -> bool:
        return execution_id in self._cancel_events

    async def run(self, task: Task) -> ExecutionRecord:
        execution = await self._executions_repo.create(task_id=task.id, project_id=task.project_id)
        cancel_event = asyncio.Event()
        self._cancel_events[execution.id] = cancel_event
        await self._events.publish(OrchestrationEvent(
            type=EventType.EXECUTION_CREATED, execution_id=execution.id, task_id=task.id,
            payload={"mode": task.mode.value},
        ))

        try:
            await self._task_service.transition(task.id, TaskStatus.RUNNING)

            if not self._provider_pool.names():
                raise ProviderUnavailableError(_NO_PROVIDER_MESSAGE)

            project = await self._project_service.get_project(task.project_id)
            workspace_path = project.workspace_path

            step_index, intent = await self._run_phase(
                execution.id, task.id, 0, ExecutionPhase.INTENT_ANALYSIS, cancel_event,
                lambda: self._intent_analyzer.analyze(task),
            )
            if cancel_event.is_set():
                return await self._finish_cancelled(execution.id, task.id)

            step_index, plan = await self._run_phase(
                execution.id, task.id, step_index, ExecutionPhase.PLANNING, cancel_event,
                lambda: self._planner.create_plan(task, intent),
            )
            await self._executions_repo.update_plan(execution.id, _plan_to_dict(plan))
            await self._events.publish(OrchestrationEvent(
                type=EventType.PLAN_CREATED, execution_id=execution.id, task_id=task.id,
                payload={"steps": len(plan.steps), "source": plan.source, "strategy": plan.strategy},
            ))
            if cancel_event.is_set():
                return await self._finish_cancelled(execution.id, task.id)

            step_index, routes = await self._run_phase(
                execution.id, task.id, step_index, ExecutionPhase.ROUTING, cancel_event,
                lambda: self._route_all(plan, intent.risk, execution.id),
            )
            if cancel_event.is_set():
                return await self._finish_cancelled(execution.id, task.id)

            step_index, results = await self._run_execution_phase(
                execution.id, task, plan, routes, workspace_path, step_index, cancel_event,
            )
            if cancel_event.is_set() or any(r.status == StepStatus.CANCELLED for r in results):
                return await self._finish_cancelled(execution.id, task.id)

            results, verification, step_index = await self._review_loop(
                execution.id, task, plan, routes, results, workspace_path, step_index, cancel_event,
            )
            if cancel_event.is_set():
                return await self._finish_cancelled(execution.id, task.id)

            _step_index, aggregated = await self._run_phase(
                execution.id, task.id, step_index, ExecutionPhase.AGGREGATION, cancel_event,
                lambda: self._aggregator.aggregate(results, verification),
            )

            any_success = any(
                r.status == StepStatus.COMPLETED and r.output for r in results
            )
            if verification.passed:
                task_status = TaskStatus.COMPLETED
            elif any_success:
                task_status = TaskStatus.PARTIAL
            else:
                task_status = TaskStatus.FAILED

            execution_status = (
                ExecutionStatus.COMPLETED if (verification.passed or any_success) else ExecutionStatus.FAILED
            )
            await self._executions_repo.update_status(
                execution.id, execution_status, completed=True,
                error=None if verification.passed else {"reasons": verification.reasons},
            )
            await self._task_service.transition(task.id, task_status, result=asdict(aggregated))

            await self._events.publish(OrchestrationEvent(
                type=EventType.EXECUTION_COMPLETED if execution_status == ExecutionStatus.COMPLETED
                else EventType.EXECUTION_FAILED,
                execution_id=execution.id, task_id=task.id,
                payload={
                    "task_status": task_status.value, "cost_usd": aggregated.total_cost_usd,
                    "tokens": aggregated.total_tokens,
                },
            ))
            return await self._executions_repo.get_or_raise(execution.id)

        except Exception as exc:  # noqa: BLE001 - deliberate top-level containment boundary
            await self._fail_execution(execution.id, task.id, exc)
            return await self._executions_repo.get_or_raise(execution.id)
        finally:
            self._cancel_events.pop(execution.id, None)
            self._budget.reset_execution(execution.id)

    # -- phase plumbing (unchanged shape from Stage 1) --------------------

    async def _run_phase(
        self,
        execution_id: str,
        task_id: str,
        step_index: int,
        phase: ExecutionPhase,
        cancel_event: asyncio.Event,
        work: Callable[[], Any] | Callable[[], Awaitable[Any]],
    ) -> tuple[int, Any]:
        label = PHASE_LABELS[phase]
        row = await self._steps_repo.create(
            execution_id=execution_id, step_index=step_index, name=label, kind="phase"
        )
        await self._emit(execution_id, task_id, phase, StepStatus.RUNNING, label)

        if cancel_event.is_set():
            await self._steps_repo.complete(row.id, StepStatus.CANCELLED)
            await self._emit(execution_id, task_id, phase, StepStatus.CANCELLED, label)
            return step_index + 1, None

        try:
            result = work()
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as exc:
            safe_message = exc.message if isinstance(exc, OrchestratorError) else str(exc)
            await self._steps_repo.complete(row.id, StepStatus.FAILED, error={"message": safe_message})
            await self._emit(execution_id, task_id, phase, StepStatus.FAILED, safe_message)
            raise

        await self._steps_repo.complete(row.id, StepStatus.COMPLETED)
        await self._emit(execution_id, task_id, phase, StepStatus.COMPLETED, label)
        return step_index + 1, result

    async def _emit(
        self, execution_id: str, task_id: str, phase: ExecutionPhase, status: StepStatus,
        detail: str | None,
    ) -> None:
        await self._phase_sink(
            ExecutionEvent(
                execution_id=execution_id, task_id=task_id, phase=phase,
                phase_label=PHASE_LABELS[phase], status=status, detail=detail,
            )
        )

    # -- routing -----------------------------------------------------------

    def _route_all(
        self, plan: ExecutionPlan, risk: RiskLevel, execution_id: str
    ) -> dict[str, RoutingDecision]:
        routes: dict[str, RoutingDecision] = {}
        for step in plan.steps:
            if step.step_type == "synthesis":
                continue
            try:
                decision = self._router.route(step, risk=risk)
            except NotFoundError:
                continue
            routes[step.id] = decision
        return routes

    async def _publish_routing_events(
        self, execution_id: str, task_id: str, plan: ExecutionPlan, routes: dict[str, RoutingDecision]
    ) -> None:
        for step in plan.steps:
            decision = routes.get(step.id)
            if decision is None:
                continue
            await self._events.publish(OrchestrationEvent(
                type=EventType.AGENT_SELECTED, execution_id=execution_id, task_id=task_id,
                payload={
                    "step_id": step.id, "agent_id": decision.agent_id, "provider": decision.provider,
                    "model": decision.model, "reason": decision.reason, "score": decision.score,
                },
            ))

    # -- system prompt resolution -------------------------------------------

    async def _resolve_system_prompt(self, agent: Agent) -> str:
        try:
            return await self._prompts.get_active_prompt(agent.id)
        except NotFoundError:
            return agent.system_prompt

    # -- execution phase (DAG, parallel layers) -----------------------------

    async def _run_execution_phase(
        self,
        execution_id: str,
        task: Task,
        plan: ExecutionPlan,
        routes: dict[str, RoutingDecision],
        workspace_path: str | None,
        step_index: int,
        cancel_event: asyncio.Event,
    ) -> tuple[int, list[StepResult]]:
        await self._publish_routing_events(execution_id, task.id, plan, routes)

        phase = ExecutionPhase.EXECUTION
        label = PHASE_LABELS[phase]
        phase_row = await self._steps_repo.create(
            execution_id=execution_id, step_index=step_index, name=label, kind="phase"
        )
        await self._emit(execution_id, task.id, phase, StepStatus.RUNNING, label)
        step_index += 1

        layers = build_execution_layers(plan.steps)
        results_by_id: dict[str, StepResult] = {}
        aborted = False

        for layer in layers:
            if cancel_event.is_set() or aborted:
                for step in layer:
                    status = StepStatus.CANCELLED if cancel_event.is_set() else StepStatus.SKIPPED
                    row = await self._steps_repo.create(
                        execution_id=execution_id, step_index=step_index, name=step.name,
                        kind="work", input_data=step.input,
                    )
                    await self._steps_repo.complete(row.id, status)
                    results_by_id[step.id] = StepResult(step_id=step.id, status=status)
                    step_index += 1
                continue

            indices = list(range(step_index, step_index + len(layer)))
            step_index += len(layer)
            step_results = await asyncio.gather(*[
                self._run_single_step(
                    execution_id, task, plan, step, routes, results_by_id, workspace_path,
                    idx, cancel_event,
                )
                for step, idx in zip(layer, indices, strict=True)
            ])
            for step, result in zip(layer, step_results, strict=True):
                results_by_id[step.id] = result
                if result.status in (StepStatus.FAILED, StepStatus.CANCELLED):
                    aborted = True

        ordered_results = [results_by_id[step.id] for step in plan.steps]
        overall_status = StepStatus.COMPLETED
        if any(r.status == StepStatus.CANCELLED for r in ordered_results):
            overall_status = StepStatus.CANCELLED
        elif any(r.status == StepStatus.FAILED for r in ordered_results):
            overall_status = StepStatus.FAILED

        await self._steps_repo.complete(phase_row.id, overall_status)
        await self._emit(execution_id, task.id, phase, overall_status, label)
        return step_index, ordered_results

    async def _run_single_step(
        self,
        execution_id: str,
        task: Task,
        plan: ExecutionPlan,
        step: PlanStep,
        routes: dict[str, RoutingDecision],
        results_by_id: dict[str, StepResult],
        workspace_path: str | None,
        step_index: int,
        cancel_event: asyncio.Event,
    ) -> StepResult:
        if step.step_type == "synthesis":
            return await self._run_synthesis_step(
                execution_id, task, plan, step, results_by_id, step_index,
            )

        routing = routes.get(step.id)
        row = await self._steps_repo.create(
            execution_id=execution_id, step_index=step_index, name=step.name, kind="work",
            agent_id=routing.agent_id if routing else None,
            provider=routing.provider if routing else None, input_data=step.input,
        )

        if routing is None:
            error = {"type": "no_route", "message": f"No agent available for capability '{step.required_capability}'."}
            await self._steps_repo.complete(row.id, StepStatus.FAILED, error=error)
            return StepResult(step_id=step.id, status=StepStatus.FAILED, error=error)

        agent = self._agents.get(routing.agent_id)
        if agent is None:
            error = {"type": "agent_missing", "message": f"Agent '{routing.agent_id}' not found."}
            await self._steps_repo.complete(row.id, StepStatus.FAILED, error=error)
            return StepResult(step_id=step.id, status=StepStatus.FAILED, agent_id=routing.agent_id, error=error)

        await self._events.publish(OrchestrationEvent(
            type=EventType.STEP_STARTED, execution_id=execution_id, task_id=task.id,
            payload={"step_id": step.id, "agent_id": agent.id},
        ))

        system_prompt = await self._resolve_system_prompt(agent)
        context = self._context_builder.build(
            goal=task.description or task.title, plan=plan, step=step,
            previous_results=list(results_by_id.values()), workspace_path=workspace_path,
        )
        tool_executor = ToolExecutor(workspace_path) if workspace_path else None

        result = await self._step_executor.run(
            step, routing, agent, system_prompt=system_prompt, context=context,
            tool_executor=tool_executor, cancel_event=cancel_event, execution_id=execution_id,
        )

        await self._steps_repo.complete(
            row.id, result.status,
            output={"text": result.output} if result.output else None,
            error=result.error, attempt=result.attempts,
        )
        await self._events.publish(OrchestrationEvent(
            type=EventType.STEP_COMPLETED, execution_id=execution_id, task_id=task.id,
            payload={
                "step_id": step.id, "agent_id": agent.id, "status": result.status.value,
                "provider": result.provider, "model": result.model,
                "input_tokens": result.usage.input_tokens if result.usage else 0,
                "output_tokens": result.usage.output_tokens if result.usage else 0,
                "estimated_cost_usd": result.cost_usd, "attempts": result.attempts,
                "success": result.status == StepStatus.COMPLETED,
            },
        ))
        return result

    async def _run_synthesis_step(
        self,
        execution_id: str,
        task: Task,
        plan: ExecutionPlan,
        step: PlanStep,
        results_by_id: dict[str, StepResult],
        step_index: int,
    ) -> StepResult:
        row = await self._steps_repo.create(
            execution_id=execution_id, step_index=step_index, name=step.name, kind="work",
            input_data=step.input,
        )
        candidates = [results_by_id[dep] for dep in step.dependencies if dep in results_by_id]
        verdict = await self._judge.judge(
            execution_id=execution_id, goal=task.description or task.title,
            candidates=candidates, risk=plan.intent.risk,
        )
        result = StepResult(
            step_id=step.id, status=StepStatus.COMPLETED, output=verdict.synthesis,
            agent_id=None, attempts=1,
        )
        await self._steps_repo.complete(
            row.id, result.status, output={"text": result.output, "reason": verdict.reason},
        )
        await self._events.publish(OrchestrationEvent(
            type=EventType.STEP_COMPLETED, execution_id=execution_id, task_id=task.id,
            payload={"step_id": step.id, "status": "completed", "reason": verdict.reason},
        ))
        return result

    # -- review / correction loop --------------------------------------------

    async def _review_loop(
        self,
        execution_id: str,
        task: Task,
        plan: ExecutionPlan,
        routes: dict[str, RoutingDecision],
        results: list[StepResult],
        workspace_path: str | None,
        step_index: int,
        cancel_event: asyncio.Event,
    ):
        verification = None
        for iteration in range(1, self.max_review_iterations + 1):
            step_index, verification = await self._run_phase(
                execution_id, task.id, step_index, ExecutionPhase.VERIFICATION, cancel_event,
                lambda current_results=results: self._verifier.verify(
                    current_results, categories=plan.intent.categories, risk=plan.intent.risk,
                    workspace_path=workspace_path,
                ),
            )
            if verification.passed or cancel_event.is_set():
                break
            if iteration == self.max_review_iterations:
                logger.warning(
                    "max_review_iterations_reached",
                    extra={"context": {"execution_id": execution_id, "iterations": iteration}},
                )
                break

            await self._events.publish(OrchestrationEvent(
                type=EventType.VERIFICATION_FAILED, execution_id=execution_id, task_id=task.id,
                payload={"iteration": iteration, "reasons": verification.reasons},
            ))
            results, step_index = await self._run_correction_round(
                execution_id, task, plan, routes, results, verification, workspace_path,
                step_index, cancel_event, iteration,
            )

        assert verification is not None
        return results, verification, step_index

    async def _run_correction_round(
        self,
        execution_id: str,
        task: Task,
        plan: ExecutionPlan,
        routes: dict[str, RoutingDecision],
        results: list[StepResult],
        verification,
        workspace_path: str | None,
        step_index: int,
        cancel_event: asyncio.Event,
        iteration: int,
    ) -> tuple[list[StepResult], int]:
        failing_step_ids = {
            c.name.removeprefix("step:") for c in verification.checks
            if not c.passed and c.name.startswith("step:")
        }
        gate_failures = [c for c in verification.checks if not c.passed and not c.name.startswith("step:")]

        base_step = next((s for s in plan.steps if s.id in failing_step_ids), plan.steps[-1])
        routing = routes.get(base_step.id)
        if routing is None:
            try:
                routing = self._router.route(base_step, risk=plan.intent.risk)
            except NotFoundError:
                return results, step_index

        description_lines = [f"Correct the following issues found during verification (round {iteration}):"]
        for step_id in failing_step_ids:
            description_lines.append(f"- Step '{step_id}' did not pass verification.")
        for gate in gate_failures:
            description_lines.append(f"- Quality gate '{gate.name}' failed: {gate.detail}")
        description_lines.append(f"Original goal: {task.description or task.title}")

        correction_step = PlanStep(
            id=new_id("step"),
            name=f"Correção (iteração {iteration})",
            description="\n".join(description_lines),
            required_capability=base_step.required_capability,
            step_type="correction",
            input={**base_step.input},
        )

        agent = self._agents.get(routing.agent_id)
        if agent is None:
            return results, step_index

        row = await self._steps_repo.create(
            execution_id=execution_id, step_index=step_index, name=correction_step.name,
            kind="work", agent_id=agent.id, provider=routing.provider, input_data=correction_step.input,
        )
        await self._events.publish(OrchestrationEvent(
            type=EventType.RETRY_STARTED, execution_id=execution_id, task_id=task.id,
            payload={"reason": "verification_failed", "iteration": iteration},
        ))

        system_prompt = await self._resolve_system_prompt(agent)
        context = self._context_builder.build(
            goal=task.description or task.title, plan=plan, step=correction_step,
            previous_results=results, workspace_path=workspace_path,
        )
        tool_executor = ToolExecutor(workspace_path) if workspace_path else None

        correction_result = await self._step_executor.run(
            correction_step, routing, agent, system_prompt=system_prompt, context=context,
            tool_executor=tool_executor, cancel_event=cancel_event, execution_id=execution_id,
        )
        await self._steps_repo.complete(
            row.id, correction_result.status,
            output={"text": correction_result.output} if correction_result.output else None,
            error=correction_result.error, attempt=correction_result.attempts,
        )
        step_index += 1

        new_results = [r for r in results if r.step_id not in failing_step_ids]
        new_results.append(correction_result)
        return new_results, step_index

    # -- terminal states -----------------------------------------------------

    async def _finish_cancelled(self, execution_id: str, task_id: str) -> ExecutionRecord:
        await self._executions_repo.update_status(execution_id, ExecutionStatus.CANCELLED, completed=True)
        task = await self._task_service.get_task(task_id)
        if task.status not in TERMINAL_TASK_STATUSES:
            await self._task_service.transition(task_id, TaskStatus.CANCELLED)
        await self._events.publish(OrchestrationEvent(
            type=EventType.EXECUTION_CANCELLED, execution_id=execution_id, task_id=task_id,
        ))
        return await self._executions_repo.get_or_raise(execution_id)

    async def _fail_execution(self, execution_id: str, task_id: str, exc: Exception) -> None:
        safe_message = exc.message if isinstance(exc, OrchestratorError) else "Internal orchestration error."
        log_event(
            logger, 40, "execution_failed_unexpectedly", execution_id=execution_id, task_id=task_id,
            error_type=type(exc).__name__,
        )
        await self._executions_repo.update_status(
            execution_id, ExecutionStatus.FAILED, completed=True, error={"message": safe_message}
        )
        task = await self._task_service.get_task(task_id)
        if task.status not in TERMINAL_TASK_STATUSES:
            await self._task_service.transition(task_id, TaskStatus.FAILED, result={"error": safe_message})
        await self._events.publish(OrchestrationEvent(
            type=EventType.EXECUTION_FAILED, execution_id=execution_id, task_id=task_id,
            payload={"error": safe_message},
        ))


def _plan_to_dict(plan: ExecutionPlan) -> dict:
    return {
        "task_id": plan.task_id,
        "strategy": plan.strategy,
        "source": plan.source,
        "intent": asdict(plan.intent) if isinstance(plan.intent, Intent) else plan.intent,
        "steps": [asdict(step) for step in plan.steps],
    }
