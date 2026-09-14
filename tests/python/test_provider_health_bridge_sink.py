"""Unit tests for `core.bridge.server.make_provider_health_bridge_sink` --
Stage 3's real fix for the gap identified while auditing the codebase:
`ProviderHealthMonitor.on_change` only ever fed the `provider_health` DB
table; the Virtual Office had no push event for "a provider just went
into cooldown" or "a provider just recovered" (spec section 20/31/41),
only a 15s conditional poll. This sink is the missing piece.
"""

from __future__ import annotations

import json

from core.bridge.server import make_provider_health_bridge_sink
from core.providers.base import ProviderHealthStatus
from core.providers.health import ProviderHealthMonitor
from core.utils.errors import ProviderAuthenticationError, ProviderRateLimitError


class FakeTransport:
    def __init__(self) -> None:
        self.written: list[dict] = []

    async def write_line(self, data: str) -> None:
        self.written.append(json.loads(data))


async def test_first_unhealthy_transition_emits_provider_rate_limited_with_real_retry_after() -> None:
    transport = FakeTransport()
    monitor = ProviderHealthMonitor()
    monitor.on_change(make_provider_health_bridge_sink(transport))

    await monitor.report_failure("codex_cli", ProviderRateLimitError("Rate limited", retry_after_seconds=42.5))

    assert len(transport.written) == 1
    message = transport.written[0]
    assert message["event"] == "provider.rate_limited"
    assert message["payload"]["providerId"] == "codex_cli"
    assert message["payload"]["status"] == ProviderHealthStatus.RATE_LIMITED.value
    assert message["payload"]["retryAfter"] == 42.5


async def test_unknown_duration_reports_retry_after_as_null_never_a_fabricated_number() -> None:
    transport = FakeTransport()
    monitor = ProviderHealthMonitor()
    monitor.on_change(make_provider_health_bridge_sink(transport))

    # An auth failure never carries a retry duration -- must surface as
    # `None`, not a made-up default.
    await monitor.report_failure("claude_code_cli", ProviderAuthenticationError("Not logged in"))

    payload = transport.written[0]["payload"]
    assert payload["retryAfter"] is None


async def test_recovery_emits_exactly_one_provider_recovered_event() -> None:
    transport = FakeTransport()
    monitor = ProviderHealthMonitor()
    monitor.on_change(make_provider_health_bridge_sink(transport))

    await monitor.report_failure("codex_cli", ProviderRateLimitError("Rate limited", retry_after_seconds=10.0))
    await monitor.report_success("codex_cli")

    events = [m["event"] for m in transport.written]
    assert events == ["provider.rate_limited", "provider.recovered"]
    assert transport.written[1]["payload"] == {"providerId": "codex_cli"}


async def test_transitioning_between_two_unhealthy_statuses_does_not_re_emit(
) -> None:
    """DEGRADED -> RATE_LIMITED is still real and unhealthy both times --
    the agent is already resting, so a second `provider.rate_limited` for
    the same still-unresolved outage would be noise, not new information.
    """
    transport = FakeTransport()
    monitor = ProviderHealthMonitor()
    monitor.on_change(make_provider_health_bridge_sink(transport))

    await monitor.report_failure("codex_cli", ProviderAuthenticationError("degraded first"))
    await monitor.report_failure("codex_cli", ProviderRateLimitError("then rate limited", retry_after_seconds=5.0))

    assert len(transport.written) == 1  # only the first unhealthy transition


async def test_each_provider_is_tracked_independently() -> None:
    transport = FakeTransport()
    monitor = ProviderHealthMonitor()
    monitor.on_change(make_provider_health_bridge_sink(transport))

    await monitor.report_failure("codex_cli", ProviderRateLimitError("x", retry_after_seconds=1.0))
    await monitor.report_success("claude_code_cli")  # a different, never-unhealthy provider

    events = [(m["event"], m["payload"]["providerId"]) for m in transport.written]
    assert events == [("provider.rate_limited", "codex_cli")]  # no spurious recovery for claude_code_cli
