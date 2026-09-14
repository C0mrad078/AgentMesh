from __future__ import annotations

from core.providers.base import ProviderHealthStatus
from core.providers.health import ProviderHealthMonitor
from core.utils.errors import ProviderAuthenticationError, ProviderRateLimitError


async def test_success_marks_online() -> None:
    monitor = ProviderHealthMonitor()
    await monitor.report_success("anthropic")
    assert monitor.status_of("anthropic") == ProviderHealthStatus.ONLINE


async def test_rate_limit_failure_marks_rate_limited() -> None:
    monitor = ProviderHealthMonitor()
    await monitor.report_failure("anthropic", ProviderRateLimitError("slow down"))
    assert monitor.status_of("anthropic") == ProviderHealthStatus.RATE_LIMITED


async def test_rate_limit_failure_threads_the_real_retry_after_into_the_snapshot() -> None:
    monitor = ProviderHealthMonitor()
    await monitor.report_failure("anthropic", ProviderRateLimitError("slow down", retry_after_seconds=17.0))
    assert monitor.snapshot("anthropic").retry_after_seconds == 17.0


async def test_retry_after_is_none_when_the_adapter_never_reported_one() -> None:
    monitor = ProviderHealthMonitor()
    await monitor.report_failure("anthropic", ProviderRateLimitError("slow down"))
    assert monitor.snapshot("anthropic").retry_after_seconds is None


async def test_retry_after_is_cleared_on_recovery() -> None:
    monitor = ProviderHealthMonitor()
    await monitor.report_failure("anthropic", ProviderRateLimitError("slow down", retry_after_seconds=17.0))
    await monitor.report_success("anthropic")
    assert monitor.snapshot("anthropic").retry_after_seconds is None


async def test_auth_failure_marks_unavailable() -> None:
    monitor = ProviderHealthMonitor()
    await monitor.report_failure("anthropic", ProviderAuthenticationError("bad key"))
    assert monitor.status_of("anthropic") == ProviderHealthStatus.UNAVAILABLE


async def test_circuit_open_overrides_explicit_status_as_unavailable() -> None:
    monitor = ProviderHealthMonitor()
    for _ in range(5):
        await monitor.report_failure("anthropic", ProviderRateLimitError("slow down"))
    assert monitor.status_of("anthropic") == ProviderHealthStatus.UNAVAILABLE
    assert monitor.is_available("anthropic") is False


async def test_unknown_provider_defaults_to_unknown() -> None:
    monitor = ProviderHealthMonitor()
    assert monitor.status_of("never-configured") == ProviderHealthStatus.UNKNOWN


async def test_on_change_callback_is_invoked() -> None:
    monitor = ProviderHealthMonitor()
    calls = []

    async def callback(provider, snapshot):
        calls.append((provider, snapshot.status))

    monitor.on_change(callback)
    await monitor.report_success("gemini")
    assert calls == [("gemini", ProviderHealthStatus.ONLINE)]


async def test_snapshot_all_returns_one_per_provider() -> None:
    monitor = ProviderHealthMonitor()
    await monitor.report_success("anthropic")
    await monitor.report_failure("gemini", ProviderRateLimitError("slow"))
    snapshots = monitor.snapshot_all(["anthropic", "gemini", "openai"])
    statuses = {s.provider: s.status for s in snapshots}
    assert statuses["anthropic"] == ProviderHealthStatus.ONLINE
    assert statuses["gemini"] == ProviderHealthStatus.RATE_LIMITED
    assert statuses["openai"] == ProviderHealthStatus.UNKNOWN
