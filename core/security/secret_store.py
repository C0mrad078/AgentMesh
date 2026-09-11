"""Secret storage abstraction.

Real credentials (provider API keys, tokens) must never be written to disk
in plaintext anywhere in this repository or in the application's own data
files. The production backend delegates to the OS-native secret manager via
the `keyring` library, which resolves to:

  * macOS   -> Keychain
  * Windows -> Credential Manager
  * Linux   -> Secret Service (or another backend the user has configured)

If no OS backend is available (e.g. a minimal CI/dev container), we fall
back to an in-memory store rather than ever persisting secrets in clear
text. That fallback is intentionally non-durable: secrets simply need to be
re-entered after a restart, which is a safe failure mode.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.utils.logging import get_logger

logger = get_logger("security.secret_store")

_SERVICE_NAME = "orquestrador"


class SecretStore(ABC):
    @abstractmethod
    async def set_secret(self, key: str, value: str) -> None: ...

    @abstractmethod
    async def get_secret(self, key: str) -> str | None: ...

    @abstractmethod
    async def delete_secret(self, key: str) -> None: ...


class OSKeyringSecretStore(SecretStore):
    """Backed by the OS-native credential manager via the `keyring` package."""

    def __init__(self, service_name: str = _SERVICE_NAME) -> None:
        self._service_name = service_name

    async def set_secret(self, key: str, value: str) -> None:
        import keyring

        keyring.set_password(self._service_name, key, value)

    async def get_secret(self, key: str) -> str | None:
        import keyring

        return keyring.get_password(self._service_name, key)

    async def delete_secret(self, key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self._service_name, key)
        except PasswordDeleteError:
            pass


class InMemorySecretStore(SecretStore):
    """Non-durable fallback used when no OS keyring backend is reachable.

    Never writes to disk. Used automatically as a fallback, and directly by
    tests that must not touch the real OS keychain.
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def set_secret(self, key: str, value: str) -> None:
        self._values[key] = value

    async def get_secret(self, key: str) -> str | None:
        return self._values.get(key)

    async def delete_secret(self, key: str) -> None:
        self._values.pop(key, None)


def create_secret_store() -> SecretStore:
    """Select the best available backend, degrading gracefully.

    Any failure to reach the OS keyring (missing backend, locked keychain
    unavailable in headless contexts, etc.) results in a logged fallback to
    the in-memory store -- never a plaintext file.
    """
    try:
        import keyring

        keyring.get_keyring()
        return OSKeyringSecretStore()
    except Exception:
        logger.warning(
            "secret_store_fallback",
            extra={"context": {"reason": "os_keyring_unavailable"}},
        )
        return InMemorySecretStore()
