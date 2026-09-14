"""Repository for the `provider_accounts` table."""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.providers.catalog import ProviderAccount, ProviderAccountCreate, ProviderAccountStatus
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_account(row: aiosqlite.Row) -> ProviderAccount:
    return ProviderAccount(
        id=row["id"],
        provider_id=row["provider_id"],
        label=row["label"],
        external_identifier=row["external_identifier"],
        status=ProviderAccountStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ProviderAccountsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, data: ProviderAccountCreate) -> ProviderAccount:
        now = utc_now().isoformat()
        account_id = new_id("pacct")
        await self._db.execute(
            """
            INSERT INTO provider_accounts (id, provider_id, label, external_identifier, status,
                                            created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id, data.provider_id, data.label, data.external_identifier,
                ProviderAccountStatus.DISCONNECTED.value, now, now,
            ),
        )
        created = await self.get(account_id)
        if created is None:
            raise RuntimeError("Provider account vanished immediately after creation.")
        return created

    async def get(self, account_id: str) -> ProviderAccount | None:
        row = await self._db.fetch_one("SELECT * FROM provider_accounts WHERE id = ?", (account_id,))
        return _row_to_account(row) if row else None

    async def get_or_raise(self, account_id: str) -> ProviderAccount:
        account = await self.get(account_id)
        if account is None:
            raise NotFoundError(f"Provider account '{account_id}' not found.")
        return account

    async def list_by_provider(self, provider_id: str) -> list[ProviderAccount]:
        rows = await self._db.fetch_all(
            "SELECT * FROM provider_accounts WHERE provider_id = ? ORDER BY created_at", (provider_id,)
        )
        return [_row_to_account(row) for row in rows]

    async def update_status(self, account_id: str, status: ProviderAccountStatus) -> ProviderAccount:
        await self.get_or_raise(account_id)
        now = utc_now().isoformat()
        await self._db.execute(
            "UPDATE provider_accounts SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, now, account_id),
        )
        return await self.get_or_raise(account_id)

    async def delete(self, account_id: str) -> None:
        await self.get_or_raise(account_id)
        await self._db.execute("DELETE FROM provider_accounts WHERE id = ?", (account_id,))
