from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiosqlite

from core.database.connection import Database
from core.reliability.backup import BackupManager, _sha256
from core.reliability.models import RestoreResult
from core.utils.errors import DatabaseError, ValidationError


class RestoreManager:
    """Validates snapshots and swaps the live DB with automatic rollback."""

    def __init__(
        self,
        db: Database,
        backup_manager: BackupManager,
        *,
        current_schema_version: int = 21,
        startup_check=None,
    ) -> None:
        self.db = db
        self.backup_manager = backup_manager
        self.current_schema_version = current_schema_version
        self.startup_check = startup_check

    async def restore(self, backup_id: str) -> RestoreResult:
        info = await self.backup_manager.get(backup_id)
        backup_path = Path(info.database_path)
        manifest = info.manifest
        if _sha256(backup_path) != manifest.sha256:
            raise ValidationError("Backup checksum does not match its manifest")
        actual_size = await asyncio.to_thread(lambda: backup_path.stat().st_size)
        if actual_size != manifest.db_size_bytes:
            raise ValidationError("Backup size does not match its manifest")
        if manifest.schema_version > self.current_schema_version:
            raise ValidationError("Backup schema is newer than this application")
        await self._verify_database(backup_path, manifest.schema_version)

        active_path = self.db.db_path
        active_path.parent.mkdir(parents=True, exist_ok=True)
        safety_path = active_path.parent / "pre_restore_backup.db"
        if safety_path.exists():
            timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            safety_path = active_path.parent / f"pre_restore_backup-{timestamp}-{uuid4().hex[:8]}.db"
        replacement = active_path.parent / f".{active_path.name}.restore-{uuid4().hex}.tmp"
        safety_tmp = active_path.parent / f".{active_path.name}.safety-{uuid4().hex}.tmp"

        await self._online_copy(self.db.connection, safety_tmp)
        try:
            os.replace(safety_tmp, safety_path)
            await self._copy_file(backup_path, replacement)
            await self.db.close()
            os.replace(replacement, active_path)
            await self.db.connect()
            if self.startup_check is not None:
                result = self.startup_check(self.db)
                if hasattr(result, "__await__"):
                    result = await result
                if result is False:
                    raise DatabaseError("Restored database failed startup verification")
            return RestoreResult(
                backup_id=backup_id,
                restored_path=str(active_path),
                safety_snapshot_path=str(safety_path),
                schema_version=manifest.schema_version,
            )
        except Exception as exc:
            replacement.unlink(missing_ok=True)
            await self.db.close()
            if safety_path.is_file():
                os.replace(safety_path, active_path)
                try:
                    await self.db.connect()
                except Exception as rollback_exc:
                    raise DatabaseError("Restore failed and safety-snapshot reconnection also failed") from rollback_exc
            raise DatabaseError("Restore failed; the previous database was restored") from exc
        finally:
            safety_tmp.unlink(missing_ok=True)
            replacement.unlink(missing_ok=True)

    async def _verify_database(self, path: Path, manifest_schema: int) -> None:
        connection = await aiosqlite.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = list(await (await connection.execute("PRAGMA integrity_check")).fetchall())
            if len(integrity) != 1 or integrity[0][0] != "ok":
                raise ValidationError("Backup database failed SQLite integrity_check")
            foreign_keys = list(await (await connection.execute("PRAGMA foreign_key_check")).fetchall())
            if foreign_keys:
                raise ValidationError("Backup database contains foreign-key violations")
            rows = await (await connection.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            tables = {str(row[0]) for row in rows}
            if manifest_schema > 0 and "schema_migrations" not in tables:
                raise ValidationError("Backup manifest schema does not match the database")
            if "schema_migrations" in tables:
                row = await (await connection.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations")).fetchone()
                actual_schema = int(row[0]) if row else 0
                if actual_schema != manifest_schema:
                    raise ValidationError("Backup manifest schema version does not match the database")
        except sqlite3.Error as exc:
            raise ValidationError("Backup file is not a readable SQLite database") from exc
        finally:
            await connection.close()

    async def _online_copy(self, source: aiosqlite.Connection, target_path: Path) -> None:
        destination = await aiosqlite.connect(str(target_path))
        try:
            await source.backup(destination)
            await destination.commit()
        finally:
            await destination.close()

    async def _copy_file(self, source_path: Path, target_path: Path) -> None:
        source = await aiosqlite.connect(f"file:{source_path}?mode=ro", uri=True)
        try:
            await self._online_copy(source, target_path)
        finally:
            await source.close()
