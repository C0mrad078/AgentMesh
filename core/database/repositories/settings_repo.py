"""Repository for the `settings` key/value table."""

from __future__ import annotations

from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.utils.time import utc_now


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str, default: Any = None) -> Any:
        row = await self._db.fetch_one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return default
        return loads(row["value"], default)

    async def get_all(self) -> dict[str, Any]:
        rows = await self._db.fetch_all("SELECT key, value FROM settings")
        return {row["key"]: loads(row["value"], None) for row in rows}

    async def set(self, key: str, value: Any) -> None:
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, dumps(value), now),
        )
