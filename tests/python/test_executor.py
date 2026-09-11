from __future__ import annotations

import asyncio

from core.orchestrator.executor import RetryPolicy, StepExecutor
from core.orchestrator.models import PlanStep, RoutingDecision, StepStatus
from core.providers.mock_provider import MockProvider, MockScenario
from core.utils.ids import new_id


def _step(**input_extra: object) -> PlanStep:
    return PlanStep(
        id=new_id("step"),
        name="Test step",
        description="do something",
        required_capability="planning",
        input={"task_id": "t1", **input_extra},
    )


def _routing(step: PlanStep) -> RoutingDecision:
    return RoutingDecision(step_id=step.id, agent_id="agent_generalist", provider="mock", reason="test")


async def test_executor_succeeds_immediately() -> None:
    provider = MockProvider()
    executor = StepExecutor(provider, RetryPolicy(max_attempts=3, timeout_seconds=1.0))
    step = _step(scenario=MockScenario.SUCCESS.value)
    result = await executor.run(step, _routing(step), provider_context=step.input)
    assert result.status == StepStatus.COMPLETED
    assert result.attempts == 1


async def test_executor_retries_and_eventually_succeeds() -> None:
    provider = MockProvider()
    executor = StepExecutor(
        provider, RetryPolicy(max_attempts=3, base_backoff_seconds=0.01, timeout_seconds=1.0)
    )
    step = _step(scenario=MockScenario.RETRY_THEN_SUCCESS.value, fail_count=1)
    result = await executor.run(step, _routing(step), provider_context=step.input)
    assert result.status == StepStatus.COMPLETED
    assert result.attempts == 2


async def test_executor_exhausts_retries_and_fails() -> None:
    provider = MockProvider()
    executor = StepExecutor(
        provider, RetryPolicy(max_attempts=3, base_backoff_seconds=0.01, timeout_seconds=1.0)
    )
    step = _step(scenario=MockScenario.PERSISTENT_ERROR.value)
    result = await executor.run(step, _routing(step), provider_context=step.input)
    assert result.status == StepStatus.FAILED
    assert result.attempts == 3
    assert result.error is not None


async def test_executor_times_out() -> None:
    provider = MockProvider()
    executor = StepExecutor(
        provider, RetryPolicy(max_attempts=1, base_backoff_seconds=0.01, timeout_seconds=0.1)
    )
    step = _step(scenario=MockScenario.TIMEOUT.value)
    result = await executor.run(step, _routing(step), provider_context=step.input)
    assert result.status == StepStatus.FAILED
    assert result.error is not None
    assert result.error["type"] == "timeout"


async def test_executor_real_cancellation_stops_before_completion() -> None:
    provider = MockProvider()
    executor = StepExecutor(
        provider, RetryPolicy(max_attempts=3, base_backoff_seconds=0.01, timeout_seconds=5.0)
    )
    step = _step(scenario=MockScenario.LATENCY.value, latency_seconds=1.0)
    cancel_event = asyncio.Event()

    async def cancel_soon() -> None:
        await asyncio.sleep(0.05)
        cancel_event.set()

    loop = asyncio.get_event_loop()
    start = loop.time()
    result, _ = await asyncio.gather(
        executor.run(step, _routing(step), provider_context=step.input, cancel_event=cancel_event),
        cancel_soon(),
    )
    elapsed = loop.time() - start

    assert result.status == StepStatus.CANCELLED
    # If cancellation weren't real, this would take ~1s (the full latency).
    assert elapsed < 0.5
