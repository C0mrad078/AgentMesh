"""Versioned SQL migration runner.

Migrations live as numbered `.sql` files under `versions/` (e.g.
`0001_initial.sql`). Applied versions are tracked in a `schema_migrations`
table so the same database file can be safely reopened and upgraded without
ever requiring manual SQL to be run by a human. Migrations are applied in
filename order inside a single transaction each, so a failure partway
through one migration cannot leave the schema half-updated.
"""

from __future__ import annotations

import re
from pathlib import Path

import aiosqlite

from core.utils.logging import get_logger

_VERSIONS_DIR = Path(__file__).parent / "versions"
_FILENAME_RE = re.compile(r"^(\d{4})_[a-zA-Z0-9_]+\.sql$")

logger = get_logger("database.migrations")


def discover_migrations() -> list[tuple[int, Path]]:
    """Return (version, path) pairs sorted by version, ascending."""
    migrations: list[tuple[int, Path]] = []
    for path in _VERSIONS_DIR.glob("*.sql"):
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise ValueError(
                f"Migration file '{path.name}' does not match the required "
                "'NNNN_description.sql' naming convention."
            )
        migrations.append((int(match.group(1)), path))
    migrations.sort(key=lambda item: item[0])
    return migrations


async def _ensure_migrations_table(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    await conn.commit()


async def applied_versions(conn: aiosqlite.Connection) -> set[int]:
    await _ensure_migrations_table(conn)
    cursor = await conn.execute("SELECT version FROM schema_migrations")
    rows = await cursor.fetchall()
    return {row[0] for row in rows}


async def run_migrations(conn: aiosqlite.Connection) -> list[int]:
    """Apply all pending migrations. Returns the list of newly applied versions."""
    await _ensure_migrations_table(conn)
    already_applied = await applied_versions(conn)
    newly_applied: list[int] = []

    for version, path in discover_migrations():
        if version in already_applied:
            continue
        sql = path.read_text(encoding="utf-8")
        logger.info("applying_migration", extra={"context": {"version": version, "file": path.name}})
        try:
            filename = path.name.replace("'", "''")
            await conn.executescript(
                "BEGIN IMMEDIATE;\n" + sql +
                f"\nINSERT INTO schema_migrations(version,filename) VALUES({version},'{filename}');\nCOMMIT;"
            )
        except Exception:
            await conn.rollback()
            logger.error(
                "migration_failed", extra={"context": {"version": version, "file": path.name}}
            )
            raise
        newly_applied.append(version)

    return newly_applied
