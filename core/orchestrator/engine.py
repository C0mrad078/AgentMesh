"""Execution Engine: drives one task through the full pipeline.

    Intent Analyzer -> Planner -> Router -> Executor -> Verifier -> Aggregator

Every phase is persisted as an `execution_steps` row and streamed to the
bridge via `EventSink` as it transitions, so the desktop UI can render the
step-by-step progress board in real time without polling. Cancellation is
cooperative and real: `request_cancel()` sets an `asyncio.Event` that is
checked between phases and threaded into `StepExecutor`, which actually
cancels the in-flight provider call rather than merely ignoring its result.

On any unexpected internal exception the engine still deterministically
marks the execution and task `failed` with a safe, generic message -- it
never leaves either stuck in `running` and never lets a raw traceback reach
the frontend.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from core.agents.registry import AgentRegistry
from core.database.repositories.execution_steps_repo import ExecutionStepsRepository
from core.database.repositories.executions_repo import ExecutionRecord, ExecutionsRepository
from core.orchestrator.aggregator import ResultAggregator
from core.orchestrator.events import EventSink, ExecutionEvent, noop_sink
from core.orchestrator.executor import RetryPolicy, StepExecutor
from core.orchestrator.intent_analyzer import IntentAnalyzer
from core.orchestrator.models import (
    PHASE_LABELS,
    ExecutionPhase,
    ExecutionPlan,
    ExecutionStatus,
    Intent,
    RoutingDecision,
    StepResult,
    StepStatus,
)
from core.orchestrator.planner import Planner
from core.orchestrator.router import Router
from core.orchestrator.verifier import Verifier
from core.providers.base import ProviderAdapter
from core.tasks.models import TERMINAL_TASK_STATUSES, Task, TaskStatus
from core.tasks.service import TaskService
from core.utils.errors import OrchestratorError
from core.utils.logging import get_logger, log_event

logger = get_logger("orchestrator.engine")


class ExecutionEngine:
    def __init__(
        self,
        executions_repo: ExecutionsRepository,
        steps_repo: ExecutionStepsRepository,
        task_service: TaskService,
        agent_registry: AgentRegistry,
        provider: ProviderAdapter,
        *,
        retry_policy: RetryPolicy | None = None,
        event_sink: EventSink = noop_sink,
    ) -> None:
        self._executions_repo = executions_repo
        self._steps_repo = steps_repo
        self._task_service = task_service
        self._intent_analyzer = IntentAnalyzer()
        self._planner = Planner()
        self._router = Router(agent_registry)
        self._step_executor = StepExecutor(provider, retry_policy)
        self._verifier = Verifier()
        self._aggregator = ResultAggregator()
        self._event_sink = event_sink
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

        try:
            await self._task_service.transition(task.id, TaskStatus.RUNNING)

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
            if cancel_event.is_set():
                return await self._finish_cancelled(execution.id, task.id)

            step_index, routes = await self._run_phase(
                execution.id, task.id, step_index, ExecutionPhase.ROUTING, cancel_event,
                lambda: [self._router.route(step) for step in plan.steps],
            )
            if cancel_event.is_set():
                return await self._finish_cancelled(execution.id, task.id)

            step_index, results = await self._run_execution_phase(
                execution.id, task.id, step_index, plan, routes, cancel_event
            )
            if cancel_event.is_set() or any(r.status == StepStatus.CANCELLED for r in results):
                return await self._finish_cancelled(execution.id, task.id)

            step_index, verification = await self._run_phase(
                execution.id, task.id, step_index, ExecutionPhase.VERIFICATION, cancel_event,
                lambda: self._verifier.verify(results),
            )

            _step_index, aggregated = await self._run_phase(
                execution.id, task.id, step_index, ExecutionPhase.AGGREGATION, cancel_event,
                lambda: self._aggregator.aggregate(results, verification),
            )

            final_status = (
                ExecutionStatus.COMPLETED if verification.passed else ExecutionStatus.FAILED
            )
            task_status = TaskStatus.COMPLETED if verification.passed else TaskStatus.FAILED

            await self._executions_repo.update_status(
                execution.id,
                final_status,
                completed=True,
                error=None if verification.passed else {"reasons": verification.reasons},
            )
            await self._task_service.transition(task.id, task_status, result=asdict(aggregated))
            return await self._executions_repo.get_or_raise(execution.id)

        except Exception as exc:  # noqa: BLE001 - deliberate top-level containment boundary
            await self._fail_execution(execution.id, task.id, exc)
            return await self._executions_repo.get_or_raise(execution.id)
        finally:
            self._cancel_events.pop(execution.id, None)

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

    async def _run_execution_phase(
        self,
        execution_id: str,
        task_id: str,
        step_index: int,
        plan: ExecutionPlan,
        routes: list[RoutingDecision],
        cancel_event: asyncio.Event,
    ) -> tuple[int, list[StepResult]]:
        phase = ExecutionPhase.EXECUTION
        label = PHASE_LABELS[phase]
        phase_row = await self._steps_repo.create(
            execution_id=execution_id, step_index=step_index, name=label, kind="phase"
        )
        await self._emit(execution_id, task_id, phase, StepStatus.RUNNING, label)
        step_index += 1

        routes_by_step = {route.step_id: route for route in routes}
        results: list[StepResult] = []
        aborted = False

        for plan_step in plan.steps:
            route = routes_by_step[plan_step.id]

            if cancel_event.is_set() or aborted:
                sub_row = await self._steps_repo.create(
                    execution_id=execution_id, step_index=step_index, name=plan_step.name,
                    kind="work", agent_id=route.agent_id, provider=route.provider,
                    input_data=plan_step.input,
                )
                status = StepStatus.CANCELLED if cancel_event.is_set() else StepStatus.SKIPPED
                await self._steps_repo.complete(sub_row.id, status)
                results.append(StepResult(step_id=plan_step.id, status=status, agent_id=route.agent_id))
                step_index += 1
                continue

            sub_row = await self._steps_repo.create(
                execution_id=execution_id, step_index=step_index, name=plan_step.name,
                kind="work", agent_id=route.agent_id, provider=route.provider,
                input_data=plan_step.input,
            )
            log_event(
                logger, 20, "work_step_started", execution_id=execution_id, task_id=task_id,
                step_id=plan_step.id, agent_id=route.agent_id,
            )
            result = await self._step_executor.run(
                plan_step, route,
                provider_context=plan_step.input,
                cancel_event=cancel_event,
                execution_id=execution_id,
            )
            await self._steps_repo.complete(
                sub_row.id, result.status,
                output={"text": result.output} if result.output else None,
                error=result.error,
                attempt=result.attempts,
            )
            results.append(result)
            step_index += 1

            if result.status in (StepStatus.FAILED, StepStatus.CANCELLED):
                aborted = True

        overall_status = StepStatus.COMPLETED
        if any(r.status == StepStatus.CANCELLED for r in results):
            overall_status = StepStatus.CANCELLED
        elif any(r.status == StepStatus.FAILED for r in results):
            overall_status = StepStatus.FAILED

        await self._steps_repo.complete(phase_row.id, overall_status)
        await self._emit(execution_id, task_id, phase, overall_status, label)
        return step_index, results

    async def _finish_cancelled(self, execution_id: str, task_id: str) -> ExecutionRecord:
        await self._executions_repo.update_status(execution_id, ExecutionStatus.CANCELLED, completed=True)
        task = await self._task_service.get_task(task_id)
        if task.status not in TERMINAL_TASK_STATUSES:
            await self._task_service.transition(task_id, TaskStatus.CANCELLED)
        return await self._executions_repo.get_or_raise(execution_id)

    async def _fail_execution(self, execution_id: str, task_id: str, exc: Exception) -> None:
        safe_message = exc.message if isinstance(exc, OrchestratorError) else "Internal orchestration error."
        logger.error(
            "execution_failed_unexpectedly",
            extra={"context": {"execution_id": execution_id, "task_id": task_id, "type": type(exc).__name__}},
        )
        await self._executions_repo.update_status(
            execution_id, ExecutionStatus.FAILED, completed=True, error={"message": safe_message}
        )
        task = await self._task_service.get_task(task_id)
        if task.status not in TERMINAL_TASK_STATUSES:
            await self._task_service.transition(task_id, TaskStatus.FAILED, result={"error": safe_message})

    async def _emit(
        self, execution_id: str, task_id: str, phase: ExecutionPhase, status: StepStatus,
        detail: str | None,
    ) -> None:
        await self._event_sink(
            ExecutionEvent(
                execution_id=execution_id, task_id=task_id, phase=phase,
                phase_label=PHASE_LABELS[phase], status=status, detail=detail,
            )
        )


def _plan_to_dict(plan: ExecutionPlan) -> dict:
    return {
        "task_id": plan.task_id,
        "strategy": plan.strategy,
        "intent": asdict(plan.intent) if isinstance(plan.intent, Intent) else plan.intent,
        "steps": [asdict(step) for step in plan.steps],
    }
