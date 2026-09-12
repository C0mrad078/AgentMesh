"""SQLite connection management.

A single `Database` instance owns one `aiosqlite.Connection` for the whole
process. SQLite handles concurrent readers well under WAL mode, and a
single-writer model avoids `database is locked` errors without needing an
external connection pool. All access goes through `Database.execute` /
`fetch_one` / `fetch_all` / `transaction`, so no SQL string is built or run
anywhere else in the codebase outside the `repositories/` package.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from core.database.migrations.runner import run_migrations
from core.utils.errors import DatabaseError
from core.utils.logging import get_logger

logger = get_logger("database.connection")


class Database:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise DatabaseError("Database used before connect() was called.")
        return self._conn

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA synchronous = NORMAL")
        # A second process (or a backup/integrity-check reader) briefly
        # holding a lock should not fail immediately -- wait up to 5s
        # before raising "database is locked", matching real desktop usage
        # (a backup can run while the app is live).
        await self._conn.execute("PRAGMA busy_timeout = 5000")
        applied = await run_migrations(self._conn)
        if applied:
            logger.info("migrations_applied", extra={"context": {"versions": applied}})

    async def quick_integrity_check(self) -> bool:
        """`PRAGMA quick_check` -- cheap enough to run on every startup
        (unlike the full `integrity_check`, which scans every index and is
        reserved for an explicit, user-triggered diagnostic)."""
        try:
            row = await self.fetch_one("PRAGMA quick_check")
        except DatabaseError:
            return False
        return row is not None and row[0] == "ok"

    async def full_integrity_check(self) -> list[str]:
        """`PRAGMA integrity_check` -- expensive on a large database;
        callers should only run this on explicit user request (see
        `database.integrity_check` bridge command), not automatically on
        every startup."""
        rows = await self.fetch_all("PRAGMA integrity_check")
        return [row[0] for row in rows]

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        try:
            cursor = await self.connection.execute(sql, params)
            await self.connection.commit()
            return cursor
        except aiosqlite.Error as exc:
            raise DatabaseError(f"Database write failed: {exc}") from exc

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        try:
            cursor = await self.connection.execute(sql, params)
            return await cursor.fetchone()
        except aiosqlite.Error as exc:
            raise DatabaseError(f"Database read failed: {exc}") from exc

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        try:
            cursor = await self.connection.execute(sql, params)
            return list(await cursor.fetchall())
        except aiosqlite.Error as exc:
            raise DatabaseError(f"Database read failed: {exc}") from exc

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Run a block of multiple statements atomically.

        On any exception, the transaction is rolled back and the original
        exception propagates so calling code can react appropriately.
        """
        try:
            yield self.connection
            await self.connection.commit()
        except Exception:
            await self.connection.rollback()
            raise
