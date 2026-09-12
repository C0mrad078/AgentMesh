from __future__ import annotations

import pytest
from core.providers.anthropic_provider import AnthropicProvider
from core.providers.credentials import (
    SUPPORTED_PROVIDERS,
    build_adapter,
    display_name_for,
    load_configured_api_keys,
    secret_key_for,
)
from core.security.secret_store import InMemorySecretStore


def test_secret_key_naming_is_namespaced_per_provider() -> None:
    assert secret_key_for("anthropic") != secret_key_for("openai")
    assert secret_key_for("anthropic") == "provider_api_key:anthropic"


def test_display_name_for_known_provider() -> None:
    assert "Claude" in display_name_for("anthropic")


def test_display_name_for_unknown_provider_falls_back_to_the_raw_name() -> None:
    assert display_name_for("unknown-provider") == "unknown-provider"


def test_build_adapter_returns_the_right_type() -> None:
    adapter = build_adapter("anthropic", "sk-test")
    assert isinstance(adapter, AnthropicProvider)


def test_build_adapter_rejects_unsupported_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported provider"):
        build_adapter("not-a-provider", "key")


async def test_load_configured_api_keys_only_returns_providers_with_a_key() -> None:
    store = InMemorySecretStore()
    await store.set_secret(secret_key_for("anthropic"), "sk-ant-test")
    keys = await load_configured_api_keys(store)
    assert keys == {"anthropic": "sk-ant-test"}


async def test_load_configured_api_keys_empty_store_returns_nothing() -> None:
    store = InMemorySecretStore()
    keys = await load_configured_api_keys(store)
    assert keys == {}


def test_all_supported_providers_have_a_display_name_and_adapter() -> None:
    for provider in SUPPORTED_PROVIDERS:
        assert display_name_for(provider) != provider
        build_adapter(provider, "test-key")
