from __future__ import annotations

import httpx
import pytest
import respx
from core.providers.base import AIRequest, ProviderHealthStatus, ToolSchema
from core.providers.gemini_provider import GeminiProvider
from core.utils.errors import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_BASE = "https://generativelanguage.googleapis.com"


def _request(**overrides) -> AIRequest:
    defaults: dict = dict(metadata={"model": "gemini-2.5-flash"})
    defaults.update(overrides)
    return AIRequest.simple(
        execution_id="exec_1", agent_id="agent_1", system_prompt="You are helpful.",
        prompt="Say hi.", **defaults,
    )


@respx.mock
async def test_execute_success_parses_text_and_usage() -> None:
    respx.post(url__regex=rf"{_BASE}/v1beta/models/.*:generateContent.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Hello!"}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 6, "candidatesTokenCount": 2},
            },
        )
    )
    provider = GeminiProvider(api_key="key-test")
    response = await provider.execute(_request())
    assert response.content == "Hello!"
    assert response.usage.input_tokens == 6
    assert response.usage.output_tokens == 2
    assert response.finish_reason == "stop"


@respx.mock
async def test_execute_parses_function_call() -> None:
    respx.post(url__regex=rf"{_BASE}/v1beta/models/.*:generateContent.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"functionCall": {"name": "SearchFiles", "args": {"q": "TODO"}}}]
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 1},
            },
        )
    )
    provider = GeminiProvider(api_key="key-test")
    response = await provider.execute(
        AIRequest.simple(
            execution_id="e", agent_id="a", system_prompt="s", prompt="p",
            metadata={"model": "gemini-2.5-flash"},
            tools=(ToolSchema(name="SearchFiles", description="search", parameters={}),),
        )
    )
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "SearchFiles"
    assert response.tool_calls[0].arguments == {"q": "TODO"}


@respx.mock
async def test_execute_raises_authentication_error_on_401() -> None:
    respx.post(url__regex=rf"{_BASE}/v1beta/models/.*:generateContent.*").mock(
        return_value=httpx.Response(401, json={"error": {"message": "API key not valid"}})
    )
    provider = GeminiProvider(api_key="bad-key")
    with pytest.raises(ProviderAuthenticationError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_rate_limit_with_retry_after() -> None:
    respx.post(url__regex=rf"{_BASE}/v1beta/models/.*:generateContent.*").mock(
        return_value=httpx.Response(
            429, headers={"retry-after": "20"}, json={"error": {"message": "quota exceeded"}}
        )
    )
    provider = GeminiProvider(api_key="key-test")
    with pytest.raises(ProviderRateLimitError) as exc_info:
        await provider.execute(_request())
    assert exc_info.value.retry_after_seconds == 20.0


@respx.mock
async def test_execute_raises_unavailable_on_500() -> None:
    respx.post(url__regex=rf"{_BASE}/v1beta/models/.*:generateContent.*").mock(
        return_value=httpx.Response(500, json={"error": {"message": "internal"}})
    )
    provider = GeminiProvider(api_key="key-test")
    with pytest.raises(ProviderUnavailableError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_timeout() -> None:
    respx.post(url__regex=rf"{_BASE}/v1beta/models/.*:generateContent.*").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    provider = GeminiProvider(api_key="key-test")
    with pytest.raises(ProviderTimeoutError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_invalid_response_when_no_candidates() -> None:
    respx.post(url__regex=rf"{_BASE}/v1beta/models/.*:generateContent.*").mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )
    provider = GeminiProvider(api_key="key-test")
    with pytest.raises(ProviderInvalidResponseError):
        await provider.execute(_request())


@respx.mock
async def test_health_check_online_when_models_list_succeeds() -> None:
    respx.get(url__regex=rf"{_BASE}/v1beta/models.*").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash"}]})
    )
    provider = GeminiProvider(api_key="key-test")
    assert await provider.health_check() == ProviderHealthStatus.ONLINE


@respx.mock
async def test_list_models_returns_names() -> None:
    respx.get(url__regex=rf"{_BASE}/v1beta/models.*").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "models/gemini-2.5-pro"}, {"name": "models/gemini-2.5-flash"}]}
        )
    )
    provider = GeminiProvider(api_key="key-test")
    assert await provider.list_models() == ["models/gemini-2.5-pro", "models/gemini-2.5-flash"]
