from __future__ import annotations

import asyncio

from core.agents.models import Agent, AgentPermissions
from core.orchestrator.budget import BudgetLimits, BudgetManager
from core.orchestrator.concurrency import ConcurrencyManager
from core.orchestrator.context_builder import ExecutionContext
from core.orchestrator.event_bus import EventBus, EventType
from core.orchestrator.executor import RetryPolicy, StepExecutor
from core.orchestrator.models import PlanStep, RoutingDecision, StepStatus
from core.providers.base import MessageRole
from core.providers.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from core.providers.health import ProviderHealthMonitor
from core.providers.mock_provider import MockProvider, MockScenario
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry
from core.tools.tool_schemas import ToolExecutor
from core.utils.ids import new_id


class _UnlimitedUsageReader:
    async def total_cost_since(self, since_iso: str) -> float:
        return 0.0


def _step(**input_extra: object) -> PlanStep:
    return PlanStep(
        id=new_id("step"), name="Test step", description="do something",
        required_capability="general", input={"task_id": "t1", **input_extra},
    )


def _routing(step: PlanStep) -> RoutingDecision:
    return RoutingDecision(
        step_id=step.id, agent_id="agent_generalist", provider="mock", model="mock-general-1",
        reason="test",
    )


def _agent(**overrides) -> Agent:
    defaults = dict(
        id="agent_generalist", name="Generalist", provider="mock", model="mock-general-1",
        system_prompt="You are helpful.", tools=["ReadFile", "ListFiles"],
        permissions=AgentPermissions(),
    )
    defaults.update(overrides)
    return Agent(**defaults)


def _context() -> ExecutionContext:
    return ExecutionContext(goal="Do the thing", current_step="do something")


def _make_executor(
    *, provider: MockProvider | None = None, policy: RetryPolicy | None = None,
    breaker_config: CircuitBreakerConfig | None = None, budget_limits: BudgetLimits | None = None,
) -> tuple[StepExecutor, ProviderHealthMonitor, EventBus, list]:
    pool = ProviderPool()
    pool.register(provider or MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker(breaker_config or CircuitBreakerConfig(failure_threshold=100)))
    concurrency = ConcurrencyManager()
    budget = BudgetManager(budget_limits or BudgetLimits(), _UnlimitedUsageReader())
    events = EventBus()
    published = []
    events.subscribe(lambda e: published.append(e))
    executor = StepExecutor(pool, health, concurrency, budget, events, ModelRegistry(), policy)
    return executor, health, events, published


async def test_executor_succeeds_immediately() -> None:
    executor, *_ = _make_executor(policy=RetryPolicy(max_attempts=3, timeout_seconds=1.0))
    step = _step(scenario=MockScenario.SUCCESS.value)
    result = await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )
    assert result.status == StepStatus.COMPLETED
    assert result.attempts == 1
    assert result.provider == "mock"
    assert result.usage is not None and result.usage.input_tokens > 0


async def test_executor_retries_and_eventually_succeeds() -> None:
    executor, *_ = _make_executor(
        policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0.01, timeout_seconds=1.0)
    )
    step = _step(scenario=MockScenario.RETRY_THEN_SUCCESS.value, fail_count=1)
    result = await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )
    assert result.status == StepStatus.COMPLETED
    assert result.attempts == 2


async def test_executor_exhausts_retries_and_fails() -> None:
    executor, *_ = _make_executor(
        policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0.01, timeout_seconds=1.0)
    )
    step = _step(scenario=MockScenario.PERSISTENT_ERROR.value)
    result = await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )
    assert result.status == StepStatus.FAILED
    assert result.attempts == 3
    assert result.error is not None


async def test_executor_times_out() -> None:
    executor, *_ = _make_executor(
        policy=RetryPolicy(max_attempts=1, base_backoff_seconds=0.01, timeout_seconds=0.1)
    )
    step = _step(scenario=MockScenario.TIMEOUT.value)
    result = await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )
    assert result.status == StepStatus.FAILED
    assert result.error is not None
    assert result.error["type"] == "timeout"


async def test_executor_invalid_response_is_not_retried() -> None:
    executor, *_ = _make_executor(
        policy=RetryPolicy(max_attempts=5, base_backoff_seconds=0.01, timeout_seconds=1.0)
    )
    step = _step(scenario=MockScenario.INVALID_RESPONSE.value)
    result = await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )
    assert result.status == StepStatus.FAILED
    assert result.attempts == 1  # non-retryable: must not consume all 5 attempts


async def test_executor_real_cancellation_stops_before_completion() -> None:
    executor, *_ = _make_executor(
        policy=RetryPolicy(max_attempts=3, base_backoff_seconds=0.01, timeout_seconds=5.0)
    )
    step = _step(scenario=MockScenario.LATENCY.value, latency_seconds=1.0)
    cancel_event = asyncio.Event()

    async def cancel_soon() -> None:
        await asyncio.sleep(0.05)
        cancel_event.set()

    loop = asyncio.get_event_loop()
    start = loop.time()
    result, _ = await asyncio.gather(
        executor.run(
            step, _routing(step), _agent(), system_prompt="sys", context=_context(),
            cancel_event=cancel_event, execution_id="exec_1",
        ),
        cancel_soon(),
    )
    elapsed = loop.time() - start

    assert result.status == StepStatus.CANCELLED
    assert elapsed < 0.5


async def test_executor_respects_circuit_breaker_open() -> None:
    executor, health, *_ = _make_executor(
        policy=RetryPolicy(max_attempts=3, timeout_seconds=1.0),
        breaker_config=CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=60),
    )
    from core.utils.errors import ProviderError

    await health.report_failure("mock", ProviderError("boom"))
    step = _step(scenario=MockScenario.SUCCESS.value)
    result = await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )
    assert result.status == StepStatus.FAILED
    assert result.error["type"] == "provider_unavailable"


async def test_executor_computes_real_cost_from_model_registry_and_records_it_in_budget() -> None:
    from core.providers.registry import ModelInfo

    registry = ModelRegistry(
        [ModelInfo(
            provider="mock", model_id="mock-general-1", display_name="Mock",
            input_cost_per_million_usd=10.0, output_cost_per_million_usd=20.0,
        )]
    )
    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker(CircuitBreakerConfig(failure_threshold=100)))
    concurrency = ConcurrencyManager()
    budget = BudgetManager(BudgetLimits(), _UnlimitedUsageReader())
    events = EventBus()
    executor = StepExecutor(pool, health, concurrency, budget, events, registry)

    step = _step(scenario=MockScenario.SUCCESS.value)
    result = await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )

    assert result.cost_usd > 0.0
    assert budget.spent_for_execution("exec_1") == result.cost_usd


async def test_executor_stops_when_budget_hard_limit_reached() -> None:
    pool = ProviderPool()
    pool.register(MockProvider())
    health = ProviderHealthMonitor(CircuitBreaker(CircuitBreakerConfig(failure_threshold=100)))
    concurrency = ConcurrencyManager()
    budget = BudgetManager(BudgetLimits(max_per_execution_usd=1.0), _UnlimitedUsageReader())
    await budget.record_spend("exec_1", 2.0)  # already over the limit
    events = EventBus()
    executor = StepExecutor(pool, health, concurrency, budget, events, ModelRegistry())

    step = _step(scenario=MockScenario.SUCCESS.value)
    result = await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )
    assert result.status == StepStatus.FAILED
    assert result.error["type"] == "budget_exceeded"


async def test_executor_publishes_provider_request_events() -> None:
    executor, _, _, published = _make_executor()
    step = _step(scenario=MockScenario.SUCCESS.value)
    await executor.run(
        step, _routing(step), _agent(), system_prompt="sys", context=_context(), execution_id="exec_1",
    )
    event_types = [e.type for e in published]
    assert EventType.PROVIDER_REQUEST_STARTED in event_types
    assert EventType.PROVIDER_REQUEST_COMPLETED in event_types


async def test_executor_runs_tool_call_loop() -> None:
    provider = MockProvider()
    executor, *_ = _make_executor(provider=provider)
    step = _step(simulate_tool_call={"name": "ReadFile", "arguments": {"path": "a.txt"}})

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.txt").write_text("file contents", encoding="utf-8")
        tool_executor = ToolExecutor(tmp)
        result = await executor.run(
            step, _routing(step), _agent(tools=["ReadFile"]), system_prompt="sys",
            context=_context(), tool_executor=tool_executor, execution_id="exec_1",
        )

    assert result.status == StepStatus.COMPLETED
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "ReadFile"
    assert result.tool_calls[0]["output"] == "file contents"
    assert result.output  # the final answer after the tool round-trip


async def test_executor_tool_call_denied_by_permissions_is_reported_to_model() -> None:
    provider = MockProvider()
    executor, *_ = _make_executor(provider=provider)
    step = _step(simulate_tool_call={"name": "WriteFile", "arguments": {"path": "a.txt", "content": "x"}})

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tool_executor = ToolExecutor(tmp)
        result = await executor.run(
            step, _routing(step), _agent(tools=["ReadFile"]), system_prompt="sys",
            context=_context(), tool_executor=tool_executor, execution_id="exec_1",
        )

    assert result.status == StepStatus.COMPLETED
    assert result.tool_calls[0]["error"] is not None


async def test_executor_redacts_secrets_in_tool_output_before_sending_to_the_provider() -> None:
    class _RecordingProvider(MockProvider):
        def __init__(self) -> None:
            super().__init__()
            self.requests: list = []

        async def execute(self, request):  # type: ignore[override]
            self.requests.append(request)
            return await super().execute(request)

    provider = _RecordingProvider()
    executor, *_ = _make_executor(provider=provider)
    step = _step(simulate_tool_call={"name": "ReadFile", "arguments": {"path": "secrets.env"}})

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "secrets.env").write_text("AWS_KEY=AKIA1234567890123456", encoding="utf-8")
        tool_executor = ToolExecutor(tmp)
        result = await executor.run(
            step, _routing(step), _agent(tools=["ReadFile"]), system_prompt="sys",
            context=_context(), tool_executor=tool_executor, execution_id="exec_1",
        )

    assert result.status == StepStatus.COMPLETED
    # The second call to the provider is the one carrying the tool result
    # back as a TOOL-role message -- that message must never contain the
    # raw secret the file actually held.
    second_call_messages = provider.requests[1].messages
    tool_messages = [m for m in second_call_messages if m.role == MessageRole.TOOL]
    assert len(tool_messages) == 1
    assert "AKIA1234567890123456" not in tool_messages[0].content
    assert "[REDACTED" in tool_messages[0].content
