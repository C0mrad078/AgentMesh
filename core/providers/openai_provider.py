"""OpenAI provider adapter (also backs the internal "Codex" role -- see
`core/agents/registry.py`: Codex Developer/Tester are just agents configured
with `provider="openai"` and a coding-oriented model from the registry).

Talks to the Chat Completions API (`POST /v1/chat/completions`) directly
over HTTP for the same testability reasons as `AnthropicProvider`.
"""

from __future__ import annotations

import json
from typing import Any

from core.providers.base import (
    AIRequest,
    AIResponse,
    MessageRole,
    TokenUsage,
    ToolCallRequest,
)
from core.providers.http_provider import HttpProviderAdapter


class OpenAIProvider(HttpProviderAdapter):
    name = "openai"
    base_url = "https://api.openai.com"

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

    def _build_http_request(self, request: AIRequest) -> tuple[str, dict, dict]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system_prompt}]
        for message in request.messages:
            if message.role == MessageRole.TOOL:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
                continue
            messages.append({"role": message.role.value, "content": message.content})

        body: dict[str, Any] = {
            "model": request.metadata.get("model"),
            "messages": messages,
        }
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        if request.structured_output_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "schema": request.structured_output_schema,
                    "strict": True,
                },
            }
        return "/v1/chat/completions", self._headers(), body

    def _parse_http_response(
        self, request: AIRequest, body: dict, duration_seconds: float
    ) -> AIResponse:
        choice = body["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""

        tool_calls = tuple(
            ToolCallRequest(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=_safe_json_loads(tc["function"].get("arguments", "{}")),
            )
            for tc in (message.get("tool_calls") or [])
        )

        usage_raw = body.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_raw.get("prompt_tokens", 0),
            output_tokens=usage_raw.get("completion_tokens", 0),
        )

        structured_output = None
        if request.structured_output_schema and content:
            try:
                structured_output = json.loads(content)
            except ValueError:
                structured_output = None

        return AIResponse(
            content=content,
            provider=self.name,
            model=body.get("model", str(request.metadata.get("model", ""))),
            finish_reason=choice.get("finish_reason") or "stop",
            usage=usage,
            duration_seconds=duration_seconds,
            tool_calls=tool_calls,
            structured_output=structured_output,
        )

    def _extract_error_message(self, status_code: int, body: dict | str) -> str:
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return str(error.get("message", "unknown error"))
        return str(body)[:300]

    async def list_models(self) -> list[str]:
        body = await self._fetch_json("/v1/models", self._headers())
        data = body.get("data", [])
        return [item["id"] for item in data if isinstance(item, dict) and "id" in item]


def _safe_json_loads(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}
