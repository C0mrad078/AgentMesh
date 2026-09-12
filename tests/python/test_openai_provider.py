from __future__ import annotations

import httpx
import pytest
import respx
from core.providers.base import AIRequest, ProviderHealthStatus, ToolSchema
from core.providers.openai_provider import OpenAIProvider
from core.utils.errors import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


def _request(**overrides) -> AIRequest:
    defaults: dict = dict(metadata={"model": "gpt-5.1-codex"})
    defaults.update(overrides)
    return AIRequest.simple(
        execution_id="exec_1", agent_id="agent_1", system_prompt="You are helpful.",
        prompt="Say hi.", **defaults,
    )


@respx.mock
async def test_execute_success_parses_content_and_usage() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Hi!"}, "finish_reason": "stop"}],
                "model": "gpt-5.1-codex",
                "usage": {"prompt_tokens": 8, "completion_tokens": 2},
            },
        )
    )
    provider = OpenAIProvider(api_key="sk-test")
    response = await provider.execute(_request())
    assert response.content == "Hi!"
    assert response.usage.input_tokens == 8
    assert response.usage.output_tokens == 2
    assert response.provider == "openai"


@respx.mock
async def test_execute_parses_tool_calls_with_json_arguments() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "RunTest", "arguments": '{"path": "tests/"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "model": "gpt-5.1-codex",
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
        )
    )
    provider = OpenAIProvider(api_key="sk-test")
    response = await provider.execute(
        AIRequest.simple(
            execution_id="e", agent_id="a", system_prompt="s", prompt="p",
            metadata={"model": "gpt-5.1-codex"},
            tools=(ToolSchema(name="RunTest", description="run", parameters={}),),
        )
    )
    assert response.content == ""
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "RunTest"
    assert response.tool_calls[0].arguments == {"path": "tests/"}


@respx.mock
async def test_execute_parses_structured_output() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": '{"ok": true}'}, "finish_reason": "stop"}
                ],
                "model": "gpt-5.1",
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            },
        )
    )
    provider = OpenAIProvider(api_key="sk-test")
    response = await provider.execute(
        _request(structured_output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}})
    )
    assert response.structured_output == {"ok": True}


@respx.mock
async def test_execute_raises_authentication_error_on_401() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid api key"}})
    )
    provider = OpenAIProvider(api_key="bad-key")
    with pytest.raises(ProviderAuthenticationError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_rate_limit_with_retry_after() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            429, headers={"retry-after": "5"}, json={"error": {"message": "rate limited"}}
        )
    )
    provider = OpenAIProvider(api_key="sk-test")
    with pytest.raises(ProviderRateLimitError) as exc_info:
        await provider.execute(_request())
    assert exc_info.value.retry_after_seconds == 5.0


@respx.mock
async def test_execute_raises_unavailable_on_500() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": {"message": "server error"}})
    )
    provider = OpenAIProvider(api_key="sk-test")
    with pytest.raises(ProviderUnavailableError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_timeout() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    provider = OpenAIProvider(api_key="sk-test")
    with pytest.raises(ProviderTimeoutError):
        await provider.execute(_request())


@respx.mock
async def test_execute_raises_invalid_response_on_missing_choices() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    provider = OpenAIProvider(api_key="sk-test")
    with pytest.raises(ProviderInvalidResponseError):
        await provider.execute(_request())


@respx.mock
async def test_health_check_online_when_models_list_succeeds() -> None:
    respx.get("https://api.openai.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gpt-5.1"}]})
    )
    provider = OpenAIProvider(api_key="sk-test")
    assert await provider.health_check() == ProviderHealthStatus.ONLINE


@respx.mock
async def test_list_models_returns_ids() -> None:
    respx.get("https://api.openai.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gpt-5.1"}, {"id": "gpt-5.1-codex"}]})
    )
    provider = OpenAIProvider(api_key="sk-test")
    assert await provider.list_models() == ["gpt-5.1", "gpt-5.1-codex"]
