"""Repository for the `provider_backends` table.

`upsert` is keyed on the real `UNIQUE (provider_id, backend_type)` schema
constraint via `INSERT ... ON CONFLICT DO UPDATE` (the same atomic pattern
`ProjectMemoriesRepository` uses, and for the same reason -- see migration
0002's comment) so refreshing a backend's live status is always a single
statement, never a check-then-write race.
"""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.providers.catalog import ProviderBackend, ProviderBackendStatus, ProviderBackendUpsert
from core.runtime.execution_backend import ExecutionBackendType
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_backend(row: aiosqlite.Row) -> ProviderBackend:
    return ProviderBackend(
        id=row["id"],
        provider_id=row["provider_id"],
        backend_type=ExecutionBackendType(row["backend_type"]),
        status=ProviderBackendStatus(row["status"]),
        detail=row["detail"],
        config=loads(row["config"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ProviderBackendsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, data: ProviderBackendUpsert) -> ProviderBackend:
        now = utc_now().isoformat()
        new_row_id = new_id("pbackend")
        await self._db.execute(
            """
            INSERT INTO provider_backends (id, provider_id, backend_type, status, detail, config,
                                            created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider_id, backend_type) DO UPDATE SET
                status = excluded.status, detail = excluded.detail, config = excluded.config,
                updated_at = excluded.updated_at
            """,
            (
                new_row_id, data.provider_id, data.backend_type.value, data.status.value,
                data.detail, dumps(data.config), now, now,
            ),
        )
        result = await self.get(data.provider_id, data.backend_type)
        if result is None:
            raise RuntimeError("Provider backend vanished immediately after upsert.")
        return result

    async def get(self, provider_id: str, backend_type: ExecutionBackendType) -> ProviderBackend | None:
        row = await self._db.fetch_one(
            "SELECT * FROM provider_backends WHERE provider_id = ? AND backend_type = ?",
            (provider_id, backend_type.value),
        )
        return _row_to_backend(row) if row else None

    async def list_by_provider(self, provider_id: str) -> list[ProviderBackend]:
        rows = await self._db.fetch_all(
            "SELECT * FROM provider_backends WHERE provider_id = ? ORDER BY backend_type", (provider_id,)
        )
        return [_row_to_backend(row) for row in rows]
