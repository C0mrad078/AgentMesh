"""Per-provider circuit breaker.

After too many consecutive failures, a provider is marked temporarily
unhealthy and calls to it are short-circuited (fail fast with
`ProviderUnavailableError`) instead of being attempted -- this protects the
budget and the user's time from hammering a provider that is clearly down,
and gives the Router a clean signal to fall back to an alternative.

States:

    CLOSED   -- normal operation, calls go through.
    OPEN     -- too many recent consecutive failures; calls are rejected
                immediately until `cooldown_seconds` has elapsed.
    HALF_OPEN -- cooldown elapsed; the next call is allowed through as a
                probe. Success closes the circuit again; failure reopens it
                (and resets the cooldown clock).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from core.utils.logging import get_logger

logger = get_logger("providers.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    state: CircuitState = CircuitState.CLOSED
    opened_at: float | None = None


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0


class CircuitBreaker:
    """Tracks one breaker per provider name."""

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._states: dict[str, _BreakerState] = {}

    def _state_for(self, provider: str) -> _BreakerState:
        return self._states.setdefault(provider, _BreakerState())

    def allow_request(self, provider: str) -> bool:
        state = self._state_for(provider)
        if state.state == CircuitState.CLOSED:
            return True

        if state.state == CircuitState.OPEN:
            assert state.opened_at is not None
            if time.monotonic() - state.opened_at >= self._config.cooldown_seconds:
                state.state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit_half_open", extra={"context": {"provider": provider}}
                )
                return True
            return False

        # HALF_OPEN: allow exactly one probe through; callers must report
        # its outcome via record_success/record_failure before another
        # `allow_request` will be evaluated meaningfully.
        return True

    def record_success(self, provider: str) -> None:
        state = self._state_for(provider)
        if state.state != CircuitState.CLOSED:
            logger.info("circuit_closed", extra={"context": {"provider": provider}})
        state.consecutive_failures = 0
        state.state = CircuitState.CLOSED
        state.opened_at = None

    def record_failure(self, provider: str) -> None:
        state = self._state_for(provider)
        state.consecutive_failures += 1

        if state.state == CircuitState.HALF_OPEN:
            state.state = CircuitState.OPEN
            state.opened_at = time.monotonic()
            logger.warning(
                "circuit_reopened", extra={"context": {"provider": provider}}
            )
            return

        if state.consecutive_failures >= self._config.failure_threshold:
            if state.state != CircuitState.OPEN:
                logger.warning(
                    "circuit_opened",
                    extra={
                        "context": {
                            "provider": provider,
                            "consecutive_failures": state.consecutive_failures,
                        }
                    },
                )
            state.state = CircuitState.OPEN
            state.opened_at = time.monotonic()

    def state_of(self, provider: str) -> CircuitState:
        return self._state_for(provider).state

    def consecutive_failures_of(self, provider: str) -> int:
        return self._state_for(provider).consecutive_failures

    def reset(self, provider: str | None = None) -> None:
        """Test helper: clear breaker state for one provider or all of them."""
        if provider is None:
            self._states.clear()
        else:
            self._states.pop(provider, None)
