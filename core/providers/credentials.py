"""Provider credential management: the one place that turns a user-entered
API key into a registered `ProviderAdapter`, and the one place that knows
the `SecretStore` key naming convention for provider credentials.

Keys are never persisted to SQLite (`provider_configs` only stores whether a
provider is enabled and which secret-store key holds its credential --
never the credential itself), never logged, and never sent to another
provider. See `core.security.secret_store.SecretStore` for where they
actually live (OS keychain / credential manager, or an in-memory fallback
that never touches disk).
"""

from __future__ import annotations

from core.providers.anthropic_provider import AnthropicProvider
from core.providers.base import ProviderAdapter
from core.providers.gemini_provider import GeminiProvider
from core.providers.openai_provider import OpenAIProvider
from core.security.secret_store import SecretStore

SUPPORTED_PROVIDERS: tuple[str, ...] = ("anthropic", "gemini", "openai")

_DISPLAY_NAMES: dict[str, str] = {
    "anthropic": "Anthropic (Claude)",
    "gemini": "Google (Gemini)",
    "openai": "OpenAI (Codex)",
}

_ADAPTER_FACTORIES: dict[str, type[ProviderAdapter]] = {
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
}


def secret_key_for(provider: str) -> str:
    return f"provider_api_key:{provider}"


def display_name_for(provider: str) -> str:
    return _DISPLAY_NAMES.get(provider, provider)


def build_adapter(provider: str, api_key: str) -> ProviderAdapter:
    factory = _ADAPTER_FACTORIES.get(provider)
    if factory is None:
        raise ValueError(f"Unsupported provider '{provider}'.")
    return factory(api_key=api_key)  # type: ignore[call-arg]


async def load_configured_api_keys(secret_store: SecretStore) -> dict[str, str]:
    """Returns {provider: api_key} for every supported provider that has a
    non-empty key currently stored in the secret store."""
    keys: dict[str, str] = {}
    for provider in SUPPORTED_PROVIDERS:
        value = await secret_store.get_secret(secret_key_for(provider))
        if value:
            keys[provider] = value
    return keys
