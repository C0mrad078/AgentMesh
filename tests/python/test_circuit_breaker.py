from __future__ import annotations

import time

from core.providers.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState


def test_starts_closed() -> None:
    breaker = CircuitBreaker()
    assert breaker.state_of("anthropic") == CircuitState.CLOSED
    assert breaker.allow_request("anthropic") is True


def test_opens_after_threshold_consecutive_failures() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60))
    for _ in range(3):
        breaker.record_failure("anthropic")
    assert breaker.state_of("anthropic") == CircuitState.OPEN
    assert breaker.allow_request("anthropic") is False


def test_success_resets_consecutive_failure_count() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60))
    breaker.record_failure("anthropic")
    breaker.record_failure("anthropic")
    breaker.record_success("anthropic")
    assert breaker.consecutive_failures_of("anthropic") == 0
    breaker.record_failure("anthropic")
    breaker.record_failure("anthropic")
    assert breaker.state_of("anthropic") == CircuitState.CLOSED


def test_half_open_after_cooldown_elapses() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=0.05))
    breaker.record_failure("anthropic")
    assert breaker.state_of("anthropic") == CircuitState.OPEN
    assert breaker.allow_request("anthropic") is False
    time.sleep(0.06)
    assert breaker.allow_request("anthropic") is True
    assert breaker.state_of("anthropic") == CircuitState.HALF_OPEN


def test_half_open_success_closes_circuit() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=0.01))
    breaker.record_failure("anthropic")
    time.sleep(0.02)
    breaker.allow_request("anthropic")
    breaker.record_success("anthropic")
    assert breaker.state_of("anthropic") == CircuitState.CLOSED


def test_half_open_failure_reopens_circuit() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=0.01))
    breaker.record_failure("anthropic")
    time.sleep(0.02)
    breaker.allow_request("anthropic")
    breaker.record_failure("anthropic")
    assert breaker.state_of("anthropic") == CircuitState.OPEN


def test_providers_are_independent() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=60))
    breaker.record_failure("anthropic")
    assert breaker.state_of("anthropic") == CircuitState.OPEN
    assert breaker.state_of("gemini") == CircuitState.CLOSED


def test_reset_clears_state() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=60))
    breaker.record_failure("anthropic")
    breaker.reset("anthropic")
    assert breaker.state_of("anthropic") == CircuitState.CLOSED
