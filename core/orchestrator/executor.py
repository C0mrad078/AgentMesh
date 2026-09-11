"""Executor.

Runs a single plan step against a provider with a uniform resilience policy:
bounded retries with exponential backoff, a hard timeout per attempt, and
real cooperative cancellation. "Real" cancellation means the in-flight
provider call is actually cancelled (`asyncio.Task.cancel()` + the
provider's own `cancel()` hook) rather than the caller merely stopping to
wait for it while the coroutine keeps running in the background.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from core.orchestrator.models import PlanStep, RoutingDecision, StepResult, StepStatus
from core.providers.base import ProviderAdapter, ProviderRequest, ProviderRequestKind
from core.providers.exceptions import ProviderError
from core.utils.logging import get_logger, log_event

logger = get_logger("orchestrator.executor")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_backoff_seconds: float = 0.05
    max_backoff_seconds: float = 2.0
    timeout_seconds: float = 10.0


class StepExecutor:
    def __init__(self, provider: ProviderAdapter, policy: RetryPolicy | None = None) -> None:
        self._provider = provider
        self._policy = policy or RetryPolicy()

    async def run(
        self,
        step: PlanStep,
        routing: RoutingDecision,
        *,
        provider_context: dict | None = None,
        cancel_event: asyncio.Event | None = None,
        execution_id: str | None = None,
    ) -> StepResult:
        cancel_event = cancel_event or asyncio.Event()
        context = dict(provider_context or {})
        context.setdefault("retry_key", step.id)
        last_error: dict | None = None

        for attempt in range(1, self._policy.max_attempts + 1):
            if cancel_event.is_set():
                return self._cancelled_result(step, routing.agent_id, attempt - 1)

            log_event(
                logger, 20, "step_attempt_started",
                execution_id=execution_id, task_id=step.input.get("task_id"),
                step_id=step.id, attempt=attempt,
            )

            request = ProviderRequest(
                kind=ProviderRequestKind.GENERATE,
                prompt=step.description,
                agent_id=routing.agent_id,
                context=context,
                timeout_seconds=self._policy.timeout_seconds,
            )

            try:
                result = await self._run_one_attempt(request, cancel_event, routing.agent_id)
            except _Cancelled:
                return self._cancelled_result(step, routing.agent_id, attempt)
            except TimeoutError:
                last_error = {"type": "timeout", "message": "Provider call exceeded timeout."}
                log_event(
                    logger, 30, "step_attempt_timeout",
                    execution_id=execution_id, step_id=step.id, attempt=attempt,
                )
            except ProviderError as exc:
                last_error = {"type": "provider_error", "message": exc.message}
                log_event(
                    logger, 30, "step_attempt_failed",
                    execution_id=execution_id, step_id=step.id, attempt=attempt,
                    error=exc.message,
                )
            else:
                return StepResult(
                    step_id=step.id,
                    status=StepStatus.COMPLETED,
                    output=result.output,
                    attempts=attempt,
                    agent_id=routing.agent_id,
                )

            if attempt < self._policy.max_attempts:
                backoff = min(
                    self._policy.base_backoff_seconds * (2 ** (attempt - 1)),
                    self._policy.max_backoff_seconds,
                )
                await self._sleep_or_cancel(backoff, cancel_event)
                if cancel_event.is_set():
                    return self._cancelled_result(step, routing.agent_id, attempt)

        return StepResult(
            step_id=step.id,
            status=StepStatus.FAILED,
            error=last_error or {"type": "unknown", "message": "All attempts failed."},
            attempts=self._policy.max_attempts,
            agent_id=routing.agent_id,
        )

    async def _run_one_attempt(
        self, request: ProviderRequest, cancel_event: asyncio.Event, agent_id: str
    ):
        provider_task = asyncio.ensure_future(self._provider.execute(request))
        cancel_wait_task = asyncio.ensure_future(cancel_event.wait())
        done, _pending = await asyncio.wait(
            {provider_task, cancel_wait_task},
            timeout=request.timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if cancel_wait_task in done:
            provider_task.cancel()
            await self._provider.cancel(request.context.get("retry_key", agent_id))
            await asyncio.gather(provider_task, return_exceptions=True)
            raise _Cancelled()

        if provider_task in done:
            cancel_wait_task.cancel()
            await asyncio.gather(cancel_wait_task, return_exceptions=True)
            return provider_task.result()

        # Neither finished within the timeout window: a real timeout.
        provider_task.cancel()
        cancel_wait_task.cancel()
        await asyncio.gather(provider_task, cancel_wait_task, return_exceptions=True)
        await self._provider.cancel(request.context.get("retry_key", agent_id))
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


class _Cancelled(Exception):
    """Internal sentinel; never escapes `StepExecutor`."""
