from __future__ import annotations

import asyncio
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from core.reliability.backup import BackupManager
from core.reliability.diagnostics import DiagnosticsCollector, diagnose_recovery
from core.reliability.restore import RestoreManager
from core.utils.errors import DatabaseError, ValidationError


async def _add_project(db, name: str) -> str:
    await db.execute(
        "INSERT INTO projects (id,name,description,status,config,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (f"project-{name}", name, "", "active", "{}", "2026-01-01", "2026-01-01"),
    )
    return f"project-{name}"


def _tamper(path: Path) -> None:
    path.write_bytes(path.read_bytes() + b"tampered")


async def test_online_backup_manifest_and_restored_integrity(tmp_db, tmp_path: Path) -> None:
    await _add_project(tmp_db, "before")
    backups = BackupManager(tmp_db, tmp_path / "backups")
    result = await backups.create()
    assert result.manifest.schema_version == 21
    assert result.manifest.app_version == "0.1.0-rc.1"
    assert result.manifest.sha256
    assert result.manifest.db_size_bytes == await asyncio.to_thread(lambda: Path(result.database_path).stat().st_size)
    assert "projects" in result.manifest.records_summary or result.manifest.tables_count > 0
    connection = sqlite3.connect(result.database_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT name FROM projects WHERE id='project-before'").fetchone()
    finally:
        connection.close()


async def test_backup_retention_preserves_protected_snapshots(tmp_db, tmp_path: Path) -> None:
    backups = BackupManager(tmp_db, tmp_path / "backups", retention_count=2)
    protected = await backups.create(protected=True)
    for _ in range(4):
        await backups.create()
    listed = await backups.list()
    assert len(listed) == 3
    assert any(item.manifest.backup_id == protected.manifest.backup_id for item in listed)


async def test_restore_swaps_database_and_keeps_pre_restore_snapshot(tmp_db, tmp_path: Path) -> None:
    await _add_project(tmp_db, "original")
    backups = BackupManager(tmp_db, tmp_path / "backups")
    snapshot = await backups.create()
    await _add_project(tmp_db, "later")

    result = await RestoreManager(tmp_db, backups).restore(snapshot.manifest.backup_id)
    assert result.safety_snapshot_path
    assert await asyncio.to_thread(Path(result.safety_snapshot_path).is_file)
    row = await tmp_db.fetch_one("SELECT id FROM projects WHERE id='project-original'")
    later = await tmp_db.fetch_one("SELECT id FROM projects WHERE id='project-later'")
    assert row is not None
    assert later is None


async def test_restore_checksum_failure_does_not_touch_active_database(tmp_db, tmp_path: Path) -> None:
    await _add_project(tmp_db, "keep")
    backups = BackupManager(tmp_db, tmp_path / "backups")
    snapshot = await backups.create()
    await asyncio.to_thread(_tamper, Path(snapshot.database_path))
    with pytest.raises(ValidationError, match="checksum"):
        await RestoreManager(tmp_db, backups).restore(snapshot.manifest.backup_id)
    assert await tmp_db.fetch_one("SELECT id FROM projects WHERE id='project-keep'")


async def test_restore_rolls_back_if_post_restore_startup_fails(tmp_db, tmp_path: Path) -> None:
    await _add_project(tmp_db, "original")
    backups = BackupManager(tmp_db, tmp_path / "backups")
    snapshot = await backups.create()
    await _add_project(tmp_db, "later")

    async def fail_startup(_db) -> bool:
        return False

    with pytest.raises(DatabaseError, match="previous database was restored"):
        await RestoreManager(tmp_db, backups, startup_check=fail_startup).restore(snapshot.manifest.backup_id)
    assert await tmp_db.fetch_one("SELECT id FROM projects WHERE id='project-original'")
    assert await tmp_db.fetch_one("SELECT id FROM projects WHERE id='project-later'")


async def test_restore_rejects_newer_schema_and_corrupt_database(tmp_db, tmp_path: Path) -> None:
    backups = BackupManager(tmp_db, tmp_path / "backups")
    snapshot = await backups.create()
    manifest_path = Path(snapshot.manifest_path)
    raw = json.loads(await asyncio.to_thread(manifest_path.read_text))
    raw["schema_version"] = 22
    await asyncio.to_thread(manifest_path.write_text, json.dumps(raw))
    with pytest.raises(ValidationError, match="newer"):
        await RestoreManager(tmp_db, backups).restore(snapshot.manifest.backup_id)


async def test_diagnostics_bundle_has_expected_files_and_redacts_sensitive_content(tmp_db, tmp_path: Path) -> None:
    collector = DiagnosticsCollector(tmp_db)
    logs = [
        json.dumps({
            "timestamp": "2026-09-21T12:00:00Z",
            "level": "INFO",
            "module": "database",
            "event": "migration_applied",
            "context": {"migration": 21, "api_key": "sk-super-secret-value"},
        }),
        json.dumps({
            "timestamp": "2026-09-21T12:00:01Z",
            "level": "ERROR",
            "module": "agent",
            "event": "private prompt: implement private logic",
            "context": {"prompt": "PRIVATE PROMPT TEXT"},
        }),
        "PRIVATE SOURCE CODE const secret = 'sk-leak-this';",
    ]
    output = tmp_path / "diagnostics.zip"
    await collector.export(
        output,
        providers=[{"name": "git", "available": True, "version": "git version 2.0"}, {"name": "provider", "token": "ghp_leak"}],
        runtime_bindings=[{"provider": "openai", "health": "healthy", "target_branch": "main", "label": "PRIVATE SOURCE", "api_key": "sk-leak"}],
        logs=logs,
    )
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert names == {
            "metadata.json", "providers.json", "runtime_bindings.json",
            "database_health.json", "logs_sanitized.log",
        }
        payload = b"\n".join(archive.read(name) for name in names)
        assert b"PRIVATE PROMPT TEXT" not in payload
        assert b"PRIVATE SOURCE" not in payload
        assert b"sk-leak" not in payload
        assert b"ghp_leak" not in payload
        assert b"api_key" not in payload


async def test_recovery_diagnostics_identify_interrupted_and_bad_backup(tmp_db, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / ".incomplete.tmp").write_text("partial")
    report = await diagnose_recovery(tmp_db, backup_dir=backup_dir)
    assert any(issue.code == "backup_interrupted" for issue in report)


async def test_recovery_diagnostics_flag_backup_checksum_and_schema(tmp_db, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backups = BackupManager(tmp_db, backup_dir)
    snapshot = await backups.create()
    await asyncio.to_thread(_tamper, Path(snapshot.database_path))
    report = await diagnose_recovery(tmp_db, backup_dir=backup_dir)
    assert any(issue.code == "checksum_invalid" for issue in report)

    raw = json.loads(await asyncio.to_thread(Path(snapshot.manifest_path).read_text))
    raw["schema_version"] = 22
    await asyncio.to_thread(Path(snapshot.manifest_path).write_text, json.dumps(raw))
    report = await diagnose_recovery(tmp_db, backup_dir=backup_dir)
    assert any(issue.code == "schema_incompatible" for issue in report)
