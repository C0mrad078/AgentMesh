"""Repository for the `provider_configs` table.

Never stores an API key -- only whether a provider is enabled and which
`SecretStore` key (`secret_ref`) holds its credential. See
`core.providers.credentials` for the key-naming convention and the code
that actually resolves a key into a live `ProviderAdapter`.
"""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.utils.ids import new_id
from core.utils.time import utc_now


class ProviderConfigsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, provider: str, *, display_name: str, secret_ref: str, enabled: bool) -> None:
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO provider_configs (id, provider, display_name, config, secret_ref, enabled,
                                           created_at, updated_at)
            VALUES (?, ?, ?, '{}', ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                display_name = excluded.display_name, secret_ref = excluded.secret_ref,
                enabled = excluded.enabled, updated_at = excluded.updated_at
            """,
            (new_id("provconf"), provider, display_name, secret_ref, int(enabled), now, now),
        )

    async def set_enabled(self, provider: str, enabled: bool) -> None:
        await self._db.execute(
            "UPDATE provider_configs SET enabled = ?, updated_at = ? WHERE provider = ?",
            (int(enabled), utc_now().isoformat(), provider),
        )

    async def get(self, provider: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM provider_configs WHERE provider = ?", (provider,))
        return dict(row) if row else None

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all("SELECT * FROM provider_configs ORDER BY provider")
        return [dict(row) for row in rows]
