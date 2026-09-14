"""Repository for the `providers` table. All provider-catalog SQL lives here."""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.providers.catalog import Provider


def _row_to_provider(row: aiosqlite.Row) -> Provider:
    return Provider(
        id=row["id"],
        name=row["name"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ProvidersRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, provider_id: str) -> Provider | None:
        row = await self._db.fetch_one("SELECT * FROM providers WHERE id = ?", (provider_id,))
        return _row_to_provider(row) if row else None

    async def get_by_name(self, name: str) -> Provider | None:
        row = await self._db.fetch_one("SELECT * FROM providers WHERE name = ?", (name,))
        return _row_to_provider(row) if row else None

    async def list(self) -> list[Provider]:
        rows = await self._db.fetch_all("SELECT * FROM providers ORDER BY name")
        return [_row_to_provider(row) for row in rows]
