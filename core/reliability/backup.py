from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

import aiosqlite

from core.database.connection import Database
from core.reliability.models import BackupInfo, BackupManifest
from core.utils.errors import DatabaseError, NotFoundError, ValidationError
from core.utils.time import utc_now

_RECORD_TABLES = (
    "missions",
    "delivery_candidates",
    "release_candidates",
    "deployment_runs",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class BackupManager:
    def __init__(
        self,
        db: Database,
        backup_dir: Path | str,
        *,
        retention_count: int = 5,
        current_schema_version: int = 21,
        app_version: str = "0.1.0-rc.1",
    ) -> None:
        if retention_count < 1:
            raise ValueError("retention_count must be at least 1")
        self.db = db
        self.backup_dir = Path(backup_dir)
        self.retention_count = retention_count
        self.current_schema_version = current_schema_version
        self.app_version = app_version

    async def create(self, *, protected: bool = False) -> BackupInfo:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        created = utc_now()
        backup_id = f"bkp-{created.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        final_db = self.backup_dir / f"{backup_id}.db"
        fd, temp_name = tempfile.mkstemp(prefix=f".{backup_id}-", suffix=".tmp", dir=self.backup_dir)
        os.close(fd)
        temp_db = Path(temp_name)
        try:
            destination = await aiosqlite.connect(str(temp_db))
            try:
                await self.db.connection.backup(destination)
                await destination.commit()
            finally:
                await destination.close()
            schema_version, table_count, counts = await self._summarize(temp_db)
            if schema_version > self.current_schema_version:
                raise ValidationError("Database schema is newer than the supported backup schema")
            os.replace(temp_db, final_db)
            manifest = BackupManifest(
                backup_id=backup_id,
                schema_version=schema_version,
                app_version=self.app_version,
                created_at=created,
                db_size_bytes=final_db.stat().st_size,
                sha256=_sha256(final_db),
                source_path=str(self.db.db_path),
                tables_count=table_count,
                records_summary=counts,
                protected=protected,
            )
            manifest_path = self._manifest_path(backup_id)
            _atomic_json(manifest_path, manifest.model_dump(mode="json"))
            await self.prune()
            return BackupInfo(manifest=manifest, database_path=str(final_db), manifest_path=str(manifest_path))
        except Exception:
            await asyncio.to_thread(temp_db.unlink, missing_ok=True)
            await asyncio.to_thread(final_db.unlink, missing_ok=True)
            await asyncio.to_thread(self._manifest_path(backup_id).unlink, missing_ok=True)
            raise

    async def list(self) -> list[BackupInfo]:
        result: list[BackupInfo] = []
        for manifest_path in self.backup_dir.glob("bkp-*.json"):
            try:
                manifest = BackupManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            database_path = self.backup_dir / f"{manifest.backup_id}.db"
            if database_path.is_file():
                result.append(BackupInfo(manifest=manifest, database_path=str(database_path), manifest_path=str(manifest_path)))
        return sorted(result, key=lambda item: item.manifest.created_at, reverse=True)

    async def get(self, backup_id: str) -> BackupInfo:
        if not re.fullmatch(r"bkp-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", backup_id):
            raise ValidationError("Invalid backup identifier")
        manifest_path = self._manifest_path(backup_id)
        database_path = self.backup_dir / f"{backup_id}.db"
        if not manifest_path.is_file() or not database_path.is_file():
            raise NotFoundError("Backup or its manifest is missing")
        try:
            manifest = BackupManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValidationError("Backup manifest is invalid") from exc
        if manifest.backup_id != backup_id:
            raise ValidationError("Backup manifest identifier mismatch")
        return BackupInfo(manifest=manifest, database_path=str(database_path), manifest_path=str(manifest_path))

    async def prune(self) -> int:
        backups = await self.list()
        unprotected = [item for item in backups if not item.manifest.protected]
        remove = unprotected[self.retention_count :]
        for item in remove:
            await asyncio.to_thread(Path(item.database_path).unlink, missing_ok=True)
            await asyncio.to_thread(Path(item.manifest_path).unlink, missing_ok=True)
        return len(remove)

    def _manifest_path(self, backup_id: str) -> Path:
        return self.backup_dir / f"{backup_id}.json"

    async def _summarize(self, path: Path) -> tuple[int, int, dict[str, int]]:
        connection = await aiosqlite.connect(str(path))
        try:
            rows = await (await connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")).fetchall()
            tables = [str(row[0]) for row in rows]
            version = 0
            if "schema_migrations" in tables:
                cursor = await connection.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations")
                row = await cursor.fetchone()
                version = int(row[0]) if row is not None else 0
            counts: dict[str, int] = {}
            for name in _RECORD_TABLES:
                if name in tables:
                    cursor = await connection.execute(f'SELECT COUNT(*) FROM "{name}"')
                    row = await cursor.fetchone()
                    counts[name] = int(row[0]) if row is not None else 0
            return version, len(tables), counts
        except sqlite3.Error as exc:
            raise DatabaseError("Could not inspect the completed backup") from exc
        finally:
            await connection.close()
