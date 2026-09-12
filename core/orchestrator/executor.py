"""Executor.

Runs a single plan step against a routed provider+model with a uniform
resilience policy: bounded retries (only for errors marked `retryable`,
respecting a rate limit's `Retry-After` when the provider gives one), a
circuit breaker consulted before every attempt, a hard per-attempt timeout,
a concurrency permit, a budget check, and real cooperative cancellation.

If the model asks for tools, they are executed (permission-checked against
`agent.tools`, dispatched through `ToolExecutor`) and fed back as new
messages for up to `_MAX_TOOL_ITERATIONS` turns before the step is
finalized -- this bounds an agent's tool-use loop the same way
`max_iterations` bounds the engine's review loop (see `ExecutionEngine`),
so a confused agent can never loop forever.

"Real" cancellation means the in-flight provider call is actually cancelled
(`asyncio.Task.cancel()` + the provider's own `cancel()` hook) rather than
the caller merely stopping to wait for it while the coroutine keeps running
in the background.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from core.agents.models import Agent
from core.orchestrator.budget import BudgetManager
from core.orchestrator.concurrency import ConcurrencyManager
from core.orchestrator.context_builder import ExecutionContext
from core.orchestrator.event_bus import EventBus, EventType, OrchestrationEvent
from core.orchestrator.models import PlanStep, RoutingDecision, StepResult, StepStatus
from core.providers.base import (
    AIMessage,
    AIRequest,
    AIResponse,
    MessageRole,
    ProviderAdapter,
    ToolCallRequest,
    ToolSchema,
)
from core.providers.exceptions import ProviderError, ProviderRateLimitError
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry
from core.tools.tool_schemas import ALL_TOOL_SCHEMAS, ToolExecutor
from core.utils.errors import BudgetExceededError
from core.utils.logging import get_logger, log_event

logger = get_logger("orchestrator.executor")

_MAX_TOOL_ITERATIONS = 5


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_backoff_seconds: float = 0.05
    max_backoff_seconds: float = 2.0
    timeout_seconds: float = 30.0


@dataclass
class _Attempt:
    """Outcome of one `_run_with_retry` call: exactly one of the two fields
    is set. Keeping this distinct from `StepResult` avoids conflating "the
    step is done" with "this one provider round-trip is done" while a tool
    loop is still in progress.
    """

    response: AIResponse | None = None
    failure: StepResult | None = None
    attempts: int = 0
    cost_usd: float = 0.0


class StepExecutor:
    def __init__(
        self,
        provider_pool: ProviderPool,
        health_monitor: ProviderHealthMonitor,
        concurrency: ConcurrencyManager,
        budget: BudgetManager,
        event_bus: EventBus,
        model_registry: ModelRegistry,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._pool = provider_pool
        self._health = health_monitor
        self._concurrency = concurrency
        self._budget = budget
        self._events = event_bus
        self._models = model_registry
        self._policy = policy or RetryPolicy()

    async def run(
        self,
        step: PlanStep,
        routing: RoutingDecision,
        agent: Agent,
        *,
        system_prompt: str,
        context: ExecutionContext,
        tool_executor: ToolExecutor | None = None,
        cancel_event: asyncio.Event | None = None,
        execution_id: str,
    ) -> StepResult:
        cancel_event = cancel_event or asyncio.Event()
        allowed_tools = frozenset(agent.tools)
        tools = tuple(ALL_TOOL_SCHEMAS[name] for name in allowed_tools if name in ALL_TOOL_SCHEMAS)

        messages: list[AIMessage] = [AIMessage(role=MessageRole.USER, content=context.to_prompt())]

        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        tool_call_log: list[dict] = []
        final_content = ""
        attempts_used = 0

        for _ in range(_MAX_TOOL_ITERATIONS):
            attempt = await self._run_with_retry(
                step, routing, agent, system_prompt, messages, tools,
                cancel_event=cancel_event, execution_id=execution_id,
            )

            if attempt.failure is not None:
                failure = attempt.failure
                failure.usage = _combine_usage(total_input_tokens, total_output_tokens)
                failure.cost_usd += total_cost
                failure.tool_calls = tool_call_log
                return failure

            assert attempt.response is not None
            response = attempt.response
            attempts_used += attempt.attempts
            final_content = response.content
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            total_cost += attempt.cost_usd

            if not response.tool_calls or tool_executor is None:
                break

            messages = [*messages, AIMessage(role=MessageRole.ASSISTANT, content=response.content)]
            for call in response.tool_calls:
                tool_call_log.append(await self._run_tool_call(
                    call, tool_executor, step=step, agent=agent, execution_id=execution_id,
                ))
                tool_result = tool_call_log[-1]
                messages = [
                    *messages,
                    AIMessage(
                        role=MessageRole.TOOL,
                        content=tool_result["error"] or _stringify(tool_result["output"]),
                        tool_call_id=call.id,
                        tool_name=call.name,
                    ),
                ]
        else:
            logger.warning(
                "tool_iteration_limit_reached",
                extra={"context": {"execution_id": execution_id, "step_id": step.id}},
            )

        return StepResult(
            step_id=step.id,
            status=StepStatus.COMPLETED,
            output=final_content,
            attempts=attempts_used,
            agent_id=agent.id,
            provider=routing.provider,
            model=routing.model,
            usage=_combine_usage(total_input_tokens, total_output_tokens),
            cost_usd=total_cost,
            tool_calls=tool_call_log,
        )

    async def _run_tool_call(
        self,
        call: ToolCallRequest,
        tool_executor: ToolExecutor,
        *,
        step: PlanStep,
        agent: Agent,
        execution_id: str,
    ) -> dict:
        await self._events.publish(OrchestrationEvent(
            type=EventType.TOOL_STARTED, execution_id=execution_id,
            payload={"step_id": step.id, "agent_id": agent.id, "tool": call.name, "arguments": call.arguments},
        ))
        result, duration = await tool_executor.execute(call, agent=agent)
        await self._events.publish(OrchestrationEvent(
            type=EventType.TOOL_COMPLETED, execution_id=execution_id,
            payload={
                "step_id": step.id, "agent_id": agent.id, "tool": call.name,
                "arguments": call.arguments, "success": result.error is None,
                "error": result.error, "duration_seconds": duration,
            },
        ))
        return {
            "id": call.id, "name": call.name, "arguments": call.arguments,
            "output": result.output, "error": result.error,
        }

    async def _run_with_retry(
        self,
        step: PlanStep,
        routing: RoutingDecision,
        agent: Agent,
        system_prompt: str,
        messages: list[AIMessage],
        tools: tuple[ToolSchema, ...],
        *,
        cancel_event: asyncio.Event,
        execution_id: str,
    ) -> _Attempt:
        last_error: dict | None = None

        for attempt_number in range(1, self._policy.max_attempts + 1):
            if cancel_event.is_set():
                return _Attempt(failure=self._cancelled_result(step, agent.id, attempt_number - 1))

            if not self._health.is_available(routing.provider):
                return _Attempt(failure=StepResult(
                    step_id=step.id, status=StepStatus.FAILED, agent_id=agent.id,
                    provider=routing.provider, model=routing.model, attempts=attempt_number,
                    error={
                        "type": "provider_unavailable",
                        "message": f"{routing.provider} is temporarily unavailable (circuit open).",
                    },
                ))

            try:
                await self._budget.check_before_call(execution_id)
            except BudgetExceededError as exc:
                return _Attempt(failure=StepResult(
                    step_id=step.id, status=StepStatus.FAILED, agent_id=agent.id,
                    provider=routing.provider, model=routing.model, attempts=attempt_number,
                    error={"type": "budget_exceeded", "message": exc.message},
                ))

            log_event(
                logger, 20, "step_attempt_started", execution_id=execution_id,
                task_id=step.input.get("task_id"), step_id=step.id, attempt=attempt_number,
            )
            await self._events.publish(OrchestrationEvent(
                type=EventType.PROVIDER_REQUEST_STARTED, execution_id=execution_id,
                payload={
                    "step_id": step.id, "agent_id": agent.id, "provider": routing.provider,
                    "model": routing.model, "attempt": attempt_number,
                },
            ))

            request = AIRequest(
                execution_id=execution_id, agent_id=agent.id, system_prompt=system_prompt,
                messages=tuple(messages), tools=tools,
                metadata={**step.input, "model": routing.model, "retry_key": step.id},
                timeout_seconds=self._policy.timeout_seconds,
            )

            try:
                provider = self._pool.get(routing.provider)
                async with self._concurrency.acquire(routing.provider, routing.model):
                    response = await self._run_one_attempt(provider, request, cancel_event, step.id)
            except _Cancelled:
                return _Attempt(failure=self._cancelled_result(step, agent.id, attempt_number))
            except TimeoutError:
                await self._health.report_failure(routing.provider, ProviderError("timeout"))
                last_error = {"type": "timeout", "message": "Provider call exceeded timeout."}
                if not await self._maybe_retry_after_failure(step, attempt_number, last_error["type"], cancel_event, execution_id):
                    return _Attempt(failure=self._cancelled_result(step, agent.id, attempt_number))
                continue
            except ProviderError as exc:
                await self._health.report_failure(routing.provider, exc)
                last_error = {"type": type(exc).__name__, "message": exc.message}
                await self._events.publish(OrchestrationEvent(
                    type=EventType.PROVIDER_REQUEST_COMPLETED, execution_id=execution_id,
                    payload={
                        "step_id": step.id, "agent_id": agent.id, "provider": routing.provider,
                        "model": routing.model, "success": False, "error": exc.message,
                    },
                ))
                if not exc.retryable:
                    return _Attempt(failure=StepResult(
                        step_id=step.id, status=StepStatus.FAILED, agent_id=agent.id,
                        provider=routing.provider, model=routing.model, attempts=attempt_number,
                        error=last_error,
                    ))
                backoff = self._backoff_for(attempt_number, exc)
                if not await self._maybe_retry_after_failure(step, attempt_number, last_error["type"], cancel_event, execution_id, backoff=backoff):
                    return _Attempt(failure=self._cancelled_result(step, agent.id, attempt_number))
                continue
            else:
                await self._health.report_success(routing.provider)
                cost_usd = self._estimate_cost(routing, response)
                await self._budget.record_spend(execution_id, cost_usd)
                await self._events.publish(OrchestrationEvent(
                    type=EventType.PROVIDER_REQUEST_COMPLETED, execution_id=execution_id,
                    payload={
                        "step_id": step.id, "agent_id": agent.id, "provider": routing.provider,
                        "model": response.model, "success": True,
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "estimated_cost_usd": cost_usd,
                        "duration_seconds": response.duration_seconds,
                    },
                ))
                return _Attempt(response=response, attempts=attempt_number, cost_usd=cost_usd)

        return _Attempt(failure=StepResult(
            step_id=step.id, status=StepStatus.FAILED, agent_id=agent.id,
            provider=routing.provider, model=routing.model,
            error=last_error or {"type": "unknown", "message": "All attempts failed."},
            attempts=self._policy.max_attempts,
        ))

    def _estimate_cost(self, routing: RoutingDecision, response: AIResponse) -> float:
        """Real cost is always derived from the Model Registry's configured
        per-token pricing, never from the adapter -- adapters normalize
        provider responses and deliberately know nothing about pricing (see
        `core.providers.base.AIResponse`), so pricing changes are a registry
        edit, not a code change in every provider.
        """
        model_info = self._models.get(routing.provider, response.model) or self._models.get(
            routing.provider, routing.model
        )
        if model_info is None:
            return 0.0
        return model_info.estimate_cost_usd(response.usage.input_tokens, response.usage.output_tokens)

    async def _maybe_retry_after_failure(
        self, step: PlanStep, attempt_number: int, reason: str, cancel_event: asyncio.Event,
        execution_id: str, *, backoff: float | None = None,
    ) -> bool:
        """Returns False if cancellation won the race and the caller should
        stop retrying; True if it is safe to loop again."""
        if attempt_number >= self._policy.max_attempts:
            return True  # loop naturally ends; the caller's final-failure path handles it
        await self._events.publish(OrchestrationEvent(
            type=EventType.RETRY_STARTED, execution_id=execution_id,
            payload={"step_id": step.id, "reason": reason, "attempt": attempt_number},
        ))
        await self._sleep_or_cancel(backoff if backoff is not None else self._backoff_for(attempt_number, None), cancel_event)
        return not cancel_event.is_set()

    def _backoff_for(self, attempt: int, exc: ProviderError | None) -> float:
        if isinstance(exc, ProviderRateLimitError) and exc.retry_after_seconds:
            return min(exc.retry_after_seconds, self._policy.max_backoff_seconds * 4)
        return min(
            self._policy.base_backoff_seconds * (2 ** (attempt - 1)), self._policy.max_backoff_seconds
        )

    async def _run_one_attempt(
        self, provider: ProviderAdapter, request: AIRequest, cancel_event: asyncio.Event, retry_key: str
    ) -> AIResponse:
        provider_task = asyncio.ensure_future(provider.execute(request))
        cancel_wait_task = asyncio.ensure_future(cancel_event.wait())
        done, _pending = await asyncio.wait(
            {provider_task, cancel_wait_task},
            timeout=request.timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if cancel_wait_task in done:
            provider_task.cancel()
            await provider.cancel(retry_key)
            await asyncio.gather(provider_task, return_exceptions=True)
            raise _Cancelled()

        if provider_task in done:
            cancel_wait_task.cancel()
            await asyncio.gather(cancel_wait_task, return_exceptions=True)
            return provider_task.result()

        provider_task.cancel()
        cancel_wait_task.cancel()
        await asyncio.gather(provider_task, cancel_wait_task, return_exceptions=True)
        await provider.cancel(retry_key)
        raise TimeoutError(f"Step exceeded timeout of {request.timeout_seconds}s")

    async def _sleep_or_cancel(self, seconds: float, cancel_event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=seconds)
        except TimeoutError:
            pass

    def _cancelled_result(self, step: PlanStep, agent_id: str, attempts: int) -> StepResult:
        return StepResult(
            step_id=step.id,
            status=StepStatus.CANCELLED,
            error={"type": "cancelled", "message": "Execution was cancelled by the user."},
            attempts=attempts,
            agent_id=agent_id,
        )


def _combine_usage(input_tokens: int, output_tokens: int):
    from core.providers.base import TokenUsage

    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)


def _stringify(value: object) -> str:
    if isinstance(value, str):
        return value
    return str(value)


class _Cancelled(Exception):
    """Internal sentinel; never escapes `StepExecutor`."""
