"""MockProvider: a configurable stand-in for a real AI provider.

Stage 1 has no real provider integrations, but the execution engine (retry,
backoff, timeout, cancellation, verification) has to be exercised against
realistic failure modes *before* real APIs exist. `MockProvider` supports six
scenarios, selected via `request.context["scenario"]`:

  * success             - returns a valid result immediately.
  * latency             - sleeps `context["latency_seconds"]` (default 0.2s)
                           before returning a valid result.
  * retry_then_success  - fails with a retryable `ProviderError` for the
                           first `context["fail_count"]` (default 1) calls
                           sharing the same `context["retry_key"]`, then
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
from collections import defaultdict
from enum import Enum

from core.providers.base import (
    ProviderAdapter,
    ProviderHealth,
    ProviderRequest,
    ProviderResult,
)
from core.providers.exceptions import ProviderError, ProviderInvalidResponseError
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


class MockProvider(ProviderAdapter):
    name = "mock"

    def __init__(self) -> None:
        self._attempt_counts: dict[str, int] = defaultdict(int)
        self._cancelled: set[str] = set()

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        scenario = MockScenario(request.context.get("scenario", MockScenario.SUCCESS.value))
        retry_key = request.context.get("retry_key", request.agent_id)

        if retry_key in self._cancelled:
            raise ProviderError("Request was cancelled before execution.")

        if scenario == MockScenario.SUCCESS:
            return self._make_result(request)

        if scenario == MockScenario.LATENCY:
            latency = float(request.context.get("latency_seconds", _DEFAULT_LATENCY_SECONDS))
            await asyncio.sleep(latency)
            return self._make_result(request)

        if scenario == MockScenario.RETRY_THEN_SUCCESS:
            fail_count = int(request.context.get("fail_count", 1))
            self._attempt_counts[retry_key] += 1
            attempt = self._attempt_counts[retry_key]
            if attempt <= fail_count:
                raise ProviderError(
                    f"Mock recoverable failure (attempt {attempt} of {fail_count})."
                )
            return self._make_result(request)

        if scenario == MockScenario.PERSISTENT_ERROR:
            self._attempt_counts[retry_key] += 1
            raise ProviderError(
                f"Mock persistent failure (attempt {self._attempt_counts[retry_key]})."
            )

        if scenario == MockScenario.TIMEOUT:
            await asyncio.sleep(request.timeout_seconds + 5.0)
            return self._make_result(request)

        if scenario == MockScenario.INVALID_RESPONSE:
            raise ProviderInvalidResponseError("Mock provider returned an unparseable payload.")

        raise ProviderError(f"Unknown mock scenario: {scenario}")

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth.HEALTHY

    async def cancel(self, request_id: str) -> None:
        self._cancelled.add(request_id)

    def _make_result(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(
            output=f"[mock:{request.agent_id}] completed: {request.prompt[:200]}",
            raw={"scenario": request.context.get("scenario", MockScenario.SUCCESS.value)},
            tokens_used=len(request.prompt.split()),
        )

    def reset(self) -> None:
        """Test helper: clear all per-key state."""
        self._attempt_counts.clear()
        self._cancelled.clear()
