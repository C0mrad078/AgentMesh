"""Google Gemini provider adapter.

Talks to the Generative Language API's `generateContent` endpoint directly
over HTTP. Two wire-format quirks worth calling out, since they differ from
Anthropic/OpenAI and are easy to get wrong:

  * the API key is passed as a `?key=` query parameter, not a header;
  * Gemini's roles are `user` and `model` (not `assistant`), and a tool
    result is sent back as a `function` role message with a
    `functionResponse` part rather than a generic "tool" role.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from core.providers.base import (
    AIRequest,
    AIResponse,
    MessageRole,
    TokenUsage,
    ToolCallRequest,
)
from core.providers.http_provider import HttpProviderAdapter

_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider(HttpProviderAdapter):
    name = "gemini"
    base_url = "https://generativelanguage.googleapis.com"

    def _build_http_request(self, request: AIRequest) -> tuple[str, dict, dict]:
        model = request.metadata.get("model", _DEFAULT_MODEL)
        contents: list[dict[str, Any]] = []
        for message in request.messages:
            if message.role == MessageRole.TOOL:
                contents.append(
                    {
                        "role": "function",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": message.tool_name or "tool",
                                    "response": {"result": message.content},
                                }
                            }
                        ],
                    }
                )
                continue
            role = "model" if message.role == MessageRole.ASSISTANT else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})

        body: dict[str, Any] = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
        }

        generation_config: dict[str, Any] = {}
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if generation_config:
            body["generationConfig"] = generation_config

        if request.tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {"name": t.name, "description": t.description, "parameters": t.parameters}
                        for t in request.tools
                    ]
                }
            ]

        path = f"/v1beta/models/{model}:generateContent?key={quote(self._api_key)}"
        return path, {"content-type": "application/json"}, body

    def _parse_http_response(
        self, request: AIRequest, body: dict, duration_seconds: float
    ) -> AIResponse:
        candidates = body.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini response had no candidates.")
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])

        text_parts = [p["text"] for p in parts if "text" in p]
        tool_calls = tuple(
            ToolCallRequest(
                id=f"gemini-call-{i}",
                name=p["functionCall"]["name"],
                arguments=p["functionCall"].get("args", {}),
            )
            for i, p in enumerate(parts)
            if "functionCall" in p
        )

        usage_raw = body.get("usageMetadata", {})
        usage = TokenUsage(
            input_tokens=usage_raw.get("promptTokenCount", 0),
            output_tokens=usage_raw.get("candidatesTokenCount", 0),
        )

        return AIResponse(
            content="".join(text_parts),
            provider=self.name,
            model=str(request.metadata.get("model", _DEFAULT_MODEL)),
            finish_reason=(candidate.get("finishReason") or "STOP").lower(),
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
        path = f"/v1beta/models?key={quote(self._api_key)}"
        body = await self._fetch_json(path, {})
        data = body.get("models", [])
        return [item["name"] for item in data if isinstance(item, dict) and "name" in item]
