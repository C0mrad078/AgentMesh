from __future__ import annotations

import pytest
from core.providers.base import ProviderConnectionState
from core.providers.provider_manager import ProviderManager


def test_cli_provider_names_lists_all_three_identities() -> None:
    manager = ProviderManager()
    assert set(manager.cli_provider_names()) == {"codex_cli", "claude_code_cli", "gemini_cli"}


def test_unknown_provider_name_raises_key_error() -> None:
    manager = ProviderManager()
    with pytest.raises(KeyError):
        manager.cli_adapter("not_a_real_provider")


async def test_list_cli_statuses_reports_every_provider_without_crashing() -> None:
    # No mocking here on purpose: this must be safe to call on any machine,
    # including one with none of the three CLIs installed -- exactly the
    # "no provider available, never crash" requirement (spec §74).
    manager = ProviderManager()
    statuses = await manager.list_cli_statuses()

    assert set(statuses.keys()) == {"codex_cli", "claude_code_cli", "gemini_cli"}
    for status in statuses.values():
        assert status.state in ProviderConnectionState
