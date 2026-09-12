"""Stage 4 database hardening: backup, restore, and integrity checks.

Matches the exact "BACKUP TEST" scenario from the brief: create a
database, add data, back it up, modify it, restore, and validate the
restored content matches the backup, not the modification.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.database.backup import create_backup, list_backups, restore_backup
from core.database.connection import Database
from core.database.repositories.projects_repo import ProjectsRepository
from core.projects.models import ProjectCreate
from core.utils.errors import DatabaseError


async def test_quick_integrity_check_passes_on_a_freshly_migrated_database(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        assert await db.quick_integrity_check() is True
    finally:
        await db.close()


async def test_full_integrity_check_reports_ok_on_a_healthy_database(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        results = await db.full_integrity_check()
        assert results == ["ok"]
    finally:
        await db.close()


async def test_backup_then_modify_then_restore_recovers_the_backed_up_content(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    db = Database(db_path)
    await db.connect()
    project = await ProjectsRepository(db).create(ProjectCreate(name="Before Backup"))
    await db.close()

    backup_info = await create_backup(db_path)
    assert backup_info.path.exists()

    # Modify the live database after the backup was taken.
    db = Database(db_path)
    await db.connect()
    await ProjectsRepository(db).create(ProjectCreate(name="After Backup"))
    await db.close()

    await restore_backup(backup_info.path, db_path)

    restored = Database(db_path)
    await restored.connect()
    try:
        projects = await ProjectsRepository(restored).list()
        names = {p.name for p in projects}
        assert names == {"Before Backup"}
        assert project.id in {p.id for p in projects}
    finally:
        await restored.close()


async def test_restore_itself_backs_up_the_pre_restore_state(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    db = Database(db_path)
    await db.connect()
    await ProjectsRepository(db).create(ProjectCreate(name="v1"))
    await db.close()

    first_backup = await create_backup(db_path)

    db = Database(db_path)
    await db.connect()
    await ProjectsRepository(db).create(ProjectCreate(name="v2"))
    await db.close()

    await restore_backup(first_backup.path, db_path)

    backups = list_backups(db_path)
    labels = [b.path.name for b in backups]
    assert any("pre_restore" in label for label in labels)


async def test_backup_retention_prunes_old_backups(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    db = Database(db_path)
    await db.connect()
    await db.close()

    for i in range(5):
        await create_backup(db_path, retention=3, label=f"n{i}")

    backups = list_backups(db_path)
    assert len(backups) == 3


async def test_backup_of_missing_database_raises(tmp_path: Path) -> None:
    with pytest.raises(DatabaseError):
        await create_backup(tmp_path / "does-not-exist.db")


async def test_restore_of_missing_backup_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    db = Database(db_path)
    await db.connect()
    await db.close()
    with pytest.raises(DatabaseError):
        await restore_backup(tmp_path / "backups" / "does-not-exist.db", db_path)


async def test_list_backups_is_empty_before_any_backup_is_made(tmp_path: Path) -> None:
    assert list_backups(tmp_path / "orchestrator.db") == []
