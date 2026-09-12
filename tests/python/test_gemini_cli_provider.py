"""Tests for the Gemini CLI stub -- see its module docstring for why
`execute()` is intentionally unimplemented rather than shipping unverified
guessed CLI flags."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.providers.base import AIRequest, ProviderConnectionState
from core.providers.exceptions import ProviderUnavailableError
from core.providers.gemini_cli_provider import GeminiCliProvider


async def test_get_status_reports_not_installed_when_binary_is_missing() -> None:
    provider = GeminiCliProvider()
    with patch.object(provider, "binary_path", return_value=None):
        status = await provider.get_status()
    assert status.state == ProviderConnectionState.NOT_INSTALLED


async def test_execute_raises_a_clear_not_implemented_error_rather_than_guessing() -> None:
    provider = GeminiCliProvider()
    request = AIRequest.simple(
        execution_id="e1", agent_id="agent_generalist", system_prompt="s", prompt="p",
    )
    with pytest.raises(ProviderUnavailableError):
        await provider.execute(request)
