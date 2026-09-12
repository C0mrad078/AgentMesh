from __future__ import annotations

import asyncio

import pytest
from core.providers.base import AIRequest, ProviderHealthStatus
from core.providers.exceptions import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderUnavailableError,
)
from core.providers.mock_provider import MockProvider, MockScenario


def _request(scenario: MockScenario, **metadata: object) -> AIRequest:
    return AIRequest.simple(
        execution_id="exec_1",
        agent_id="agent_generalist",
        system_prompt="You are a helpful assistant.",
        prompt="do the thing",
        metadata={"scenario": scenario.value, **metadata},
        timeout_seconds=1.0,
    )


async def test_success_scenario() -> None:
    provider = MockProvider()
    result = await provider.execute(_request(MockScenario.SUCCESS))
    assert "completed" in result.content
    assert result.provider == "mock"
    assert result.usage.input_tokens > 0


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

    with pytest.raises(ProviderUnavailableError):
        await provider.execute(request)

    result = await provider.execute(request)
    assert "completed" in result.content


async def test_persistent_error_always_fails() -> None:
    provider = MockProvider()
    request = _request(MockScenario.PERSISTENT_ERROR, retry_key="k2")
    for _ in range(3):
        with pytest.raises(ProviderUnavailableError):
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


async def test_health_check_reports_online() -> None:
    provider = MockProvider()
    assert await provider.health_check() == ProviderHealthStatus.ONLINE


async def test_list_models_returns_mock_models() -> None:
    provider = MockProvider()
    models = await provider.list_models()
    assert "mock-general-1" in models


async def test_cancel_prevents_future_execution() -> None:
    provider = MockProvider()
    await provider.cancel("agent_generalist")
    with pytest.raises(ProviderError):
        await provider.execute(_request(MockScenario.SUCCESS, retry_key="agent_generalist"))


async def test_stream_yields_the_full_content_in_pieces() -> None:
    provider = MockProvider()
    chunks = [chunk async for chunk in provider.stream(_request(MockScenario.SUCCESS))]
    assert "".join(chunks).strip() != ""


async def test_simulate_tool_call_returns_tool_call_on_first_turn() -> None:
    provider = MockProvider()
    request = AIRequest.simple(
        execution_id="e", agent_id="a", system_prompt="s", prompt="p",
        metadata={"simulate_tool_call": {"name": "ReadFile", "arguments": {"path": "a.txt"}}},
    )
    response = await provider.execute(request)
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "ReadFile"


async def test_simulate_tool_call_answers_normally_after_tool_result() -> None:
    from core.providers.base import AIMessage, MessageRole

    provider = MockProvider()
    request = AIRequest(
        execution_id="e", agent_id="a", system_prompt="s",
        messages=(
            AIMessage(role=MessageRole.USER, content="p"),
            AIMessage(role=MessageRole.ASSISTANT, content=""),
            AIMessage(role=MessageRole.TOOL, content="file contents", tool_call_id="mock_tool_1", tool_name="ReadFile"),
        ),
        metadata={"simulate_tool_call": {"name": "ReadFile", "arguments": {"path": "a.txt"}}},
    )
    response = await provider.execute(request)
    assert response.tool_calls == ()
    assert response.content
