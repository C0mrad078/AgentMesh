from __future__ import annotations

from pathlib import Path

import pytest
from core.database.connection import Database
from core.database.migrations.runner import applied_versions, discover_migrations


async def test_migrations_run_on_fresh_database(tmp_db: Database) -> None:
    versions = await applied_versions(tmp_db.connection)
    discovered = {v for v, _ in discover_migrations()}
    assert discovered.issubset(versions)
    assert 1 in versions


async def test_can_create_database_from_scratch(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    assert not db_path.exists()
    db = Database(db_path)
    await db.connect()
    try:
        row = await db.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name='projects'")
        assert row is not None
    finally:
        await db.close()
    assert db_path.exists()


async def test_reopening_existing_database_does_not_reapply_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "reopen.db"
    db1 = Database(db_path)
    await db1.connect()
    await db1.execute(
        "INSERT INTO projects (id, name, description, status, config, created_at, updated_at) "
        "VALUES ('p1', 'Test', '', 'active', '{}', '2024-01-01', '2024-01-01')"
    )
    await db1.close()

    db2 = Database(db_path)
    await db2.connect()
    try:
        row = await db2.fetch_one("SELECT * FROM projects WHERE id = 'p1'")
        assert row is not None
        assert row["name"] == "Test"
    finally:
        await db2.close()


async def test_foreign_keys_enforced(tmp_db: Database) -> None:
    from core.utils.errors import DatabaseError

    raised = False
    try:
        await tmp_db.execute(
            "INSERT INTO tasks (id, project_id, title, description, mode, status, input, "
            "created_at, updated_at) VALUES ('t1', 'missing-project', 'x', '', 'automatic', "
            "'queued', '{}', '2024-01-01', '2024-01-01')"
        )
    except DatabaseError:
        raised = True
    assert raised


async def test_transaction_commits_all_statements_together(tmp_db: Database) -> None:
    async with tmp_db.transaction() as conn:
        await conn.execute(
            "INSERT INTO projects (id, name, description, status, config, created_at, updated_at) "
            "VALUES ('tx1', 'A', '', 'active', '{}', '2024-01-01', '2024-01-01')"
        )
        await conn.execute(
            "INSERT INTO projects (id, name, description, status, config, created_at, updated_at) "
            "VALUES ('tx2', 'B', '', 'active', '{}', '2024-01-01', '2024-01-01')"
        )

    rows = await tmp_db.fetch_all("SELECT id FROM projects WHERE id IN ('tx1', 'tx2')")
    assert {row["id"] for row in rows} == {"tx1", "tx2"}


async def test_transaction_rolls_back_entirely_on_error(tmp_db: Database) -> None:
    with pytest.raises(RuntimeError):
        async with tmp_db.transaction() as conn:
            await conn.execute(
                "INSERT INTO projects (id, name, description, status, config, created_at, updated_at) "
                "VALUES ('tx3', 'C', '', 'active', '{}', '2024-01-01', '2024-01-01')"
            )
            raise RuntimeError("simulated failure mid-transaction")

    row = await tmp_db.fetch_one("SELECT id FROM projects WHERE id = 'tx3'")
    assert row is None
