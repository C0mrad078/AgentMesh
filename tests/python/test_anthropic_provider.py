from __future__ import annotations

import httpx
import pytest
import respx
from core.providers.anthropic_provider import AnthropicProvider
from core.providers.base import AIRequest, ProviderHealthStatus, ToolSchema
from core.utils.errors import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


def _request(**overrides) -> AIRequest:
    defaults: dict = dict(metadata={"model": "claude-sonnet-5"})
    defaults.update(overrides)
    return AIRequest.simple(
        execution_id="exec_1", agent_id="agent_1", system_prompt="You are helpful.",
        prompt="Say hi.", **defaults,
    )


@respx.mock
async def test_execute_success_parses_text_and_usage() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Hello there."}],
                "model": "claude-sonnet-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
    )
    provider = AnthropicProvider(api_key="sk-test")
    response = await provider.execute(_request())
    assert response.content == "Hello there."
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    assert response.provider == "anthropic"
    assert response.finish_reason == "end_turn"


@respx.mock
async def test_execute_parses_tool_calls() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "tu_1", "name": "ReadFile", "input": {"path": "a.py"}},
                ],
                "model": "claude-sonnet-5",
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )
    )
    provider = AnthropicProvider(api_key="sk-test")
    response = await provider.execute(
        AIRequest.simple(
            execution_id="e", agent_id="a", system_prompt="s", prompt="p",
            metadata={"model": "claude-sonnet-5"},
            tools=(ToolSchema(name="ReadFile", description="read", parameters={}),),
        )
    )
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "ReadFile"
    assert response.tool_calls[0].arguments == {"path": "a.py"}


@respx.mock
async def test_execute_raises_authentication_error_on_401() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})
    )
    provider = AnthropicProvider(api_key="bad-key")
    with pytest.raises(ProviderAuthenticationError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_rate_limit_with_retry_after() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            429, headers={"retry-after": "12"}, json={"error": {"message": "rate limited"}}
        )
    )
    provider = AnthropicProvider(api_key="sk-test")
    with pytest.raises(ProviderRateLimitError) as exc_info:
        await provider.execute(_request())
    assert exc_info.value.retry_after_seconds == 12.0


@respx.mock
async def test_execute_raises_unavailable_on_500() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(500, json={"error": {"message": "internal error"}})
    )
    provider = AnthropicProvider(api_key="sk-test")
    with pytest.raises(ProviderUnavailableError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_timeout() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    provider = AnthropicProvider(api_key="sk-test")
    with pytest.raises(ProviderTimeoutError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_invalid_response_on_malformed_json() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, content=b"not json")
    )
    provider = AnthropicProvider(api_key="sk-test")
    with pytest.raises(ProviderInvalidResponseError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_invalid_response_on_unexpected_shape() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    provider = AnthropicProvider(api_key="sk-test")
    with pytest.raises(ProviderInvalidResponseError):
        await provider.execute(_request())


@respx.mock
async def test_health_check_online_when_models_list_succeeds() -> None:
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})
    )
    provider = AnthropicProvider(api_key="sk-test")
    assert await provider.health_check() == ProviderHealthStatus.ONLINE


@respx.mock
async def test_health_check_unavailable_on_auth_failure() -> None:
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    provider = AnthropicProvider(api_key="bad-key")
    assert await provider.health_check() == ProviderHealthStatus.UNAVAILABLE


@respx.mock
async def test_list_models_returns_ids() -> None:
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "claude-opus-5"}, {"id": "claude-sonnet-5"}]}
        )
    )
    provider = AnthropicProvider(api_key="sk-test")
    models = await provider.list_models()
    assert models == ["claude-opus-5", "claude-sonnet-5"]
