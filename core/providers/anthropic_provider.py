"""Anthropic (Claude) provider adapter.

Talks to the Messages API (`POST /v1/messages`) directly over HTTP rather
than through the `anthropic` SDK -- this keeps the dependency footprint
small and, more importantly, keeps the wire format fully under our control
for deterministic testing (see `tests/python/test_anthropic_provider.py`,
which mocks the HTTP transport and never makes a real network call).
"""

from __future__ import annotations

from typing import Any

from core.providers.base import (
    AIRequest,
    AIResponse,
    MessageRole,
    TokenUsage,
    ToolCallRequest,
)
from core.providers.http_provider import HttpProviderAdapter

_API_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(HttpProviderAdapter):
    name = "anthropic"
    base_url = "https://api.anthropic.com"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

    def _build_http_request(self, request: AIRequest) -> tuple[str, dict, dict]:
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            if message.role == MessageRole.SYSTEM:
                continue
            if message.role == MessageRole.TOOL:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content,
                            }
                        ],
                    }
                )
                continue
            messages.append({"role": message.role.value, "content": message.content})

        body: dict[str, Any] = {
            "model": request.metadata.get("model"),
            "system": request.system_prompt,
            "messages": messages,
            "max_tokens": request.max_tokens or _DEFAULT_MAX_TOKENS,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in request.tools
            ]
        return "/v1/messages", self._headers(), body

    def _parse_http_response(
        self, request: AIRequest, body: dict, duration_seconds: float
    ) -> AIResponse:
        blocks = body["content"]
        text = "".join(b["text"] for b in blocks if b.get("type") == "text")
        tool_calls = tuple(
            ToolCallRequest(id=b["id"], name=b["name"], arguments=b.get("input", {}))
            for b in blocks
            if b.get("type") == "tool_use"
        )
        usage_raw = body.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
        )
        return AIResponse(
            content=text,
            provider=self.name,
            model=body.get("model", str(request.metadata.get("model", ""))),
            finish_reason=body.get("stop_reason") or "stop",
            usage=usage,
            duration_seconds=duration_seconds,
            tool_calls=tool_calls,
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
