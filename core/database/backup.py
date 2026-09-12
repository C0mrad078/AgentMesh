"""Versioned SQLite backups.

Uses SQLite's own online backup API (`sqlite3.Connection.backup`), which is
safe to run against a live database in WAL mode without stopping writers --
it takes a read snapshot page-by-page rather than copying the file bytes,
so a backup can never observe a half-written page. The blocking `sqlite3`
calls run in a worker thread (`asyncio.to_thread`) so they never stall the
event loop the bridge server runs on.

Backups are named by timestamp (`YYYY-MM-DD-HHMMSS.db`) under a
`backups/` directory next to the live database, and `create_backup` prunes
down to `retention` most-recent files afterward -- "não acumule backups
indefinidamente".
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.utils.errors import DatabaseError

_DEFAULT_RETENTION = 10


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created_at: str
    size_bytes: int


def _backup_dir_for(db_path: Path) -> Path:
    return db_path.parent / "backups"


def _do_backup(source_path: Path, dest_path: Path) -> None:
    source = sqlite3.connect(str(source_path))
    try:
        dest = sqlite3.connect(str(dest_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _do_integrity_check(db_path: Path) -> bool:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("PRAGMA quick_check").fetchone()
        return bool(row) and row[0] == "ok"
    finally:
        conn.close()


async def create_backup(
    db_path: Path, *, retention: int = _DEFAULT_RETENTION, label: str | None = None,
) -> BackupInfo:
    if not await asyncio.to_thread(db_path.exists):
        raise DatabaseError(f"Cannot back up '{db_path}': it does not exist.")

    backup_dir = _backup_dir_for(db_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    dest_path = backup_dir / f"{timestamp}{suffix}.db"

    await asyncio.to_thread(_do_backup, db_path, dest_path)

    # A backup that doesn't even pass its own quick_check is worse than no
    # backup (it would give false confidence) -- verify before keeping it.
    ok = await asyncio.to_thread(_do_integrity_check, dest_path)
    if not ok:
        dest_path.unlink(missing_ok=True)
        raise DatabaseError("Backup failed its own integrity check and was discarded.")

    _prune_old_backups(backup_dir, retention)

    stat = dest_path.stat()
    return BackupInfo(path=dest_path, created_at=timestamp, size_bytes=stat.st_size)


def _prune_old_backups(backup_dir: Path, retention: int) -> None:
    backups = sorted(backup_dir.glob("*.db"), key=lambda p: p.name, reverse=True)
    for stale in backups[retention:]:
        stale.unlink(missing_ok=True)


def list_backups(db_path: Path) -> list[BackupInfo]:
    backup_dir = _backup_dir_for(db_path)
    if not backup_dir.exists():
        return []
    infos = []
    for path in sorted(backup_dir.glob("*.db"), key=lambda p: p.name, reverse=True):
        stat = path.stat()
        infos.append(BackupInfo(path=path, created_at=path.stem, size_bytes=stat.st_size))
    return infos


async def restore_backup(backup_path: Path, target_db_path: Path) -> None:
    """Replace `target_db_path` with `backup_path`'s content.

    Only safe to call while nothing holds `target_db_path` open -- the
    caller (see the `database.backup.restore` bridge handler) is
    responsible for closing the live `Database` connection first and
    reconnecting afterward, since swapping the file out from under an open
    connection would corrupt the live connection's view of it.

    The current state is itself backed up first (`label="pre_restore"`) so
    a restore is never a one-way door.
    """
    if not await asyncio.to_thread(backup_path.exists):
        raise DatabaseError(f"Backup '{backup_path}' does not exist.")
    ok = await asyncio.to_thread(_do_integrity_check, backup_path)
    if not ok:
        raise DatabaseError(f"Backup '{backup_path}' failed its integrity check; refusing to restore it.")

    if await asyncio.to_thread(target_db_path.exists):
        await create_backup(target_db_path, label="pre_restore")

    await asyncio.to_thread(shutil.copy2, backup_path, target_db_path)
    # Drop any stale WAL/SHM sidecar files from the previous database --
    # they belong to the old file's write-ahead log, not the restored one.
    for suffix in ("-wal", "-shm"):
        sidecar = target_db_path.with_name(target_db_path.name + suffix)
        sidecar.unlink(missing_ok=True)
