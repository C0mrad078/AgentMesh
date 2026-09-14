"""Provider health monitoring.

Combines circuit-breaker state (derived from consecutive failures) with the
most recent explicit signal from a call (rate limited, auth failure,
timeout, success) into the single `ProviderHealthStatus` the Router
consults before picking a provider, and that the UI's provider panel shows
("Claude Online", "Gemini Online", "OpenAI Rate limited").
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from core.providers.base import ProviderHealthStatus
from core.providers.circuit_breaker import CircuitBreaker, CircuitState
from core.utils.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from core.utils.logging import get_logger

logger = get_logger("providers.health")


@dataclass
class ProviderHealthSnapshot:
    provider: str
    status: ProviderHealthStatus
    last_error: str | None
    consecutive_failures: int
    # Real backoff data from the adapter that raised `ProviderRateLimitError`
    # (Stage 3, spec section 31/36) -- `None` when the provider didn't
    # report a duration, or when the current status isn't RATE_LIMITED at
    # all (kept so a consumer never has to distinguish "no error" from "no
    # timing info" by any means other than `status`).
    retry_after_seconds: float | None = None


class ProviderHealthMonitor:
    def __init__(self, circuit_breaker: CircuitBreaker | None = None) -> None:
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._explicit_status: dict[str, ProviderHealthStatus] = {}
        self._last_error: dict[str, str | None] = {}
        self._retry_after: dict[str, float | None] = {}
        self._on_change: list = []

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._circuit_breaker

    def on_change(self, callback) -> None:
        """Register a (sync or async) callback invoked with (provider, snapshot)
        whenever a provider's health is updated -- used to persist to the
        `provider_health` table without coupling this class to the database.
        """
        self._on_change.append(callback)

    async def report_success(self, provider: str) -> None:
        self._circuit_breaker.record_success(provider)
        self._explicit_status[provider] = ProviderHealthStatus.ONLINE
        self._last_error[provider] = None
        self._retry_after[provider] = None
        await self._notify(provider)

    async def report_failure(self, provider: str, error: ProviderError) -> None:
        self._circuit_breaker.record_failure(provider)

        if isinstance(error, ProviderRateLimitError):
            self._explicit_status[provider] = ProviderHealthStatus.RATE_LIMITED
            self._retry_after[provider] = error.retry_after_seconds
        elif isinstance(error, ProviderAuthenticationError):
            self._explicit_status[provider] = ProviderHealthStatus.UNAVAILABLE
            self._retry_after[provider] = None
        elif isinstance(error, (ProviderTimeoutError, ProviderUnavailableError)):
            self._explicit_status[provider] = ProviderHealthStatus.DEGRADED
            self._retry_after[provider] = None
        else:
            self._explicit_status[provider] = ProviderHealthStatus.DEGRADED
            self._retry_after[provider] = None

        self._last_error[provider] = error.message
        await self._notify(provider)

    def status_of(self, provider: str) -> ProviderHealthStatus:
        if self._circuit_breaker.state_of(provider) == CircuitState.OPEN:
            return ProviderHealthStatus.UNAVAILABLE
        return self._explicit_status.get(provider, ProviderHealthStatus.UNKNOWN)

    def is_available(self, provider: str) -> bool:
        return self._circuit_breaker.allow_request(provider)

    def snapshot(self, provider: str) -> ProviderHealthSnapshot:
        return ProviderHealthSnapshot(
            provider=provider,
            status=self.status_of(provider),
            last_error=self._last_error.get(provider),
            consecutive_failures=self._circuit_breaker.consecutive_failures_of(provider),
            retry_after_seconds=self._retry_after.get(provider),
        )

    def snapshot_all(self, providers: list[str]) -> list[ProviderHealthSnapshot]:
        return [self.snapshot(p) for p in providers]

    async def _notify(self, provider: str) -> None:
        snapshot = self.snapshot(provider)
        for callback in self._on_change:
            try:
                result = callback(provider, snapshot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.error(
                    "health_change_callback_failed", extra={"context": {"provider": provider}}
                )
