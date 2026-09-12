"""MockProvider: a configurable stand-in for a real AI provider.

The execution engine (retry, backoff, timeout, cancellation, verification,
routing, budget) has to be exercised against realistic failure modes without
depending on real APIs (cost, flakiness, non-determinism). `MockProvider`
supports six scenarios, selected via `request.metadata["scenario"]`:

  * success             - returns a valid result immediately.
  * latency             - sleeps `metadata["latency_seconds"]` (default 0.2s)
                           before returning a valid result.
  * retry_then_success  - fails with a retryable `ProviderError` for the
                           first `metadata["fail_count"]` (default 1) calls
                           sharing the same `metadata["retry_key"]`, then
                           succeeds. Used to exercise the executor's retry
                           path end-to-end.
  * persistent_error    - always fails with a retryable `ProviderError`, to
                           exercise "all retries exhausted" behavior.
  * timeout             - sleeps longer than `request.timeout_seconds` so the
                           executor's own `asyncio.wait_for` deadline (not a
                           fake timeout raised here) is what fires.
  * invalid_response     - raises `ProviderInvalidResponseError` to simulate a
                           provider returning an unparseable payload.

State (retry counters, cancellation flags) is tracked per `retry_key` so
concurrent/parallel steps don't interfere with each other.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from enum import Enum

from core.providers.base import (
    AIRequest,
    AIResponse,
    MessageRole,
    ProviderAdapter,
    ProviderHealthStatus,
    TokenUsage,
    ToolCallRequest,
)
from core.providers.exceptions import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderUnavailableError,
)
from core.utils.logging import get_logger

logger = get_logger("providers.mock")


class MockScenario(str, Enum):
    SUCCESS = "success"
    LATENCY = "latency"
    RETRY_THEN_SUCCESS = "retry_then_success"
    PERSISTENT_ERROR = "persistent_error"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"


_DEFAULT_LATENCY_SECONDS = 0.2
_MOCK_MODELS = ["mock-general-1", "mock-review-1", "mock-code-1"]


class MockProvider(ProviderAdapter):
    name = "mock"

    def __init__(self) -> None:
        self._attempt_counts: dict[str, int] = defaultdict(int)
        self._cancelled: set[str] = set()

    async def execute(self, request: AIRequest) -> AIResponse:
        scenario = MockScenario(request.metadata.get("scenario", MockScenario.SUCCESS.value))
        retry_key = request.metadata.get("retry_key", request.agent_id)
        start = time.monotonic()

        if retry_key in self._cancelled:
            raise ProviderError("Request was cancelled before execution.")

        if scenario == MockScenario.SUCCESS:
            return self._make_result(request, start)

        if scenario == MockScenario.LATENCY:
            latency = float(request.metadata.get("latency_seconds", _DEFAULT_LATENCY_SECONDS))
            await asyncio.sleep(latency)
            return self._make_result(request, start)

        if scenario == MockScenario.RETRY_THEN_SUCCESS:
            fail_count = int(request.metadata.get("fail_count", 1))
            self._attempt_counts[retry_key] += 1
            attempt = self._attempt_counts[retry_key]
            if attempt <= fail_count:
                raise ProviderUnavailableError(
                    f"Mock recoverable failure (attempt {attempt} of {fail_count})."
                )
            return self._make_result(request, start)

        if scenario == MockScenario.PERSISTENT_ERROR:
            self._attempt_counts[retry_key] += 1
            raise ProviderUnavailableError(
                f"Mock persistent failure (attempt {self._attempt_counts[retry_key]})."
            )

        if scenario == MockScenario.TIMEOUT:
            await asyncio.sleep(request.timeout_seconds + 5.0)
            return self._make_result(request, start)

        if scenario == MockScenario.INVALID_RESPONSE:
            raise ProviderInvalidResponseError("Mock provider returned an unparseable payload.")

        raise ProviderError(f"Unknown mock scenario: {scenario}")

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        result = await self.execute(request)
        for word in result.content.split(" "):
            yield word + " "

    async def health_check(self) -> ProviderHealthStatus:
        return ProviderHealthStatus.ONLINE

    async def list_models(self) -> list[str]:
        return list(_MOCK_MODELS)

    async def cancel(self, execution_id: str) -> None:
        self._cancelled.add(execution_id)

    def _make_result(self, request: AIRequest, start: float) -> AIResponse:
        prompt_text = " ".join(m.content for m in request.messages)
        input_tokens = len(prompt_text.split())

        # Test/demo hook: metadata["simulate_tool_call"] = {"name": ..., "arguments": {...}}
        # triggers one tool call on the *first* turn (before any tool result
        # has come back), so `StepExecutor`'s tool-use loop can be exercised
        # end-to-end without a real provider. Once a TOOL-role message is
        # present, the mock behaves as if the model is satisfied and answers
        # normally instead of looping forever.
        already_used_tool = any(m.role == MessageRole.TOOL for m in request.messages)
        simulated_call = request.metadata.get("simulate_tool_call")
        if simulated_call and not already_used_tool:
            return AIResponse(
                content="",
                provider=self.name,
                model=str(request.metadata.get("model", "mock-general-1")),
                finish_reason="tool_use",
                usage=TokenUsage(input_tokens=input_tokens, output_tokens=0),
                duration_seconds=time.monotonic() - start,
                tool_calls=(
                    ToolCallRequest(
                        id="mock_tool_1",
                        name=simulated_call["name"],
                        arguments=simulated_call.get("arguments", {}),
                    ),
                ),
                metadata={"scenario": MockScenario.SUCCESS.value},
            )

        output_text = f"[mock:{request.agent_id}] completed: {prompt_text[:200]}"
        return AIResponse(
            content=output_text,
            provider=self.name,
            model=str(request.metadata.get("model", "mock-general-1")),
            finish_reason="stop",
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=len(output_text.split())),
            duration_seconds=time.monotonic() - start,
            estimated_cost_usd=0.0,
            metadata={"scenario": request.metadata.get("scenario", MockScenario.SUCCESS.value)},
        )

    def reset(self) -> None:
        """Test helper: clear all per-key state."""
        self._attempt_counts.clear()
        self._cancelled.clear()
