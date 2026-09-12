"""Repository for the `provider_health` table -- persists
`ProviderHealthMonitor` snapshots so the UI's provider panel survives a
restart without needing a fresh health check first."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.utils.time import utc_now


class ProviderHealthRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self, provider: str, status: str, *, last_error: str | None, consecutive_failures: int
    ) -> None:
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO provider_health (provider, status, last_error, consecutive_failures, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                status = excluded.status, last_error = excluded.last_error,
                consecutive_failures = excluded.consecutive_failures, updated_at = excluded.updated_at
            """,
            (provider, status, last_error, consecutive_failures, now),
        )

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all("SELECT * FROM provider_health ORDER BY provider")
        return [dict(row) for row in rows]
