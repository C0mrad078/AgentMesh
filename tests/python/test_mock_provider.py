from __future__ import annotations

import asyncio

import pytest
from core.providers.base import ProviderHealth, ProviderRequest, ProviderRequestKind
from core.providers.exceptions import ProviderError, ProviderInvalidResponseError
from core.providers.mock_provider import MockProvider, MockScenario


def _request(scenario: MockScenario, **context: object) -> ProviderRequest:
    return ProviderRequest(
        kind=ProviderRequestKind.GENERATE,
        prompt="do the thing",
        agent_id="agent_generalist",
        context={"scenario": scenario.value, **context},
        timeout_seconds=1.0,
    )


async def test_success_scenario() -> None:
    provider = MockProvider()
    result = await provider.execute(_request(MockScenario.SUCCESS))
    assert "completed" in result.output


async def test_latency_scenario_takes_at_least_the_configured_time() -> None:
    provider = MockProvider()
    loop = asyncio.get_event_loop()
    start = loop.time()
    await provider.execute(_request(MockScenario.LATENCY, latency_seconds=0.05))
    elapsed = loop.time() - start
    assert elapsed >= 0.05


async def test_retry_then_success_fails_then_succeeds() -> None:
    provider = MockProvider()
    request = _request(MockScenario.RETRY_THEN_SUCCESS, fail_count=1, retry_key="k1")

    with pytest.raises(ProviderError):
        await provider.execute(request)

    result = await provider.execute(request)
    assert "completed" in result.output


async def test_persistent_error_always_fails() -> None:
    provider = MockProvider()
    request = _request(MockScenario.PERSISTENT_ERROR, retry_key="k2")
    for _ in range(3):
        with pytest.raises(ProviderError):
            await provider.execute(request)


async def test_timeout_scenario_outlasts_requested_timeout() -> None:
    provider = MockProvider()
    request = _request(MockScenario.TIMEOUT)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(provider.execute(request), timeout=request.timeout_seconds)


async def test_invalid_response_scenario_raises() -> None:
    provider = MockProvider()
    with pytest.raises(ProviderInvalidResponseError):
        await provider.execute(_request(MockScenario.INVALID_RESPONSE))


async def test_health_check_reports_healthy() -> None:
    provider = MockProvider()
    assert await provider.health_check() == ProviderHealth.HEALTHY


async def test_cancel_prevents_future_execution() -> None:
    provider = MockProvider()
    await provider.cancel("agent_generalist")
    with pytest.raises(ProviderError):
        await provider.execute(_request(MockScenario.SUCCESS, retry_key="agent_generalist"))
