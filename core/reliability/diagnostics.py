from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from core import __version__
from core.database.connection import Database
from core.reliability.models import RecoveryIssue
from core.security.secret_scanner import SecretScanner
from core.utils.errors import DatabaseError

_SECRET_KEY = re.compile(
    r"(?i)(authorization|cookie|x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"secret|password|credential|private[_-]?key|\.env|prompt|source[_-]?code)"
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|sk-[A-Za-z0-9_-]{10,}|"
    r"\bBearer\s+\S+|-----BEGIN [^-]*PRIVATE KEY-----|"
    r"(?:postgres|postgresql|mysql)://[^\s/:]+:[^\s@]+@|"
    r"(?:[A-Za-z]:\\|/Users/|/home/)[^\s]+)"
)
_SAFE_CONTEXT_KEYS = {
    "execution_id", "task_id", "provider", "operation", "status", "duration_ms",
    "attempt", "retry", "count", "version", "migration", "command", "available",
    "exit_code", "phase", "level", "event_id",
}
_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_SAFE_EVENT = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def sanitize_text(value: str) -> str:
    """Redact secrets and private/path-like values from one text value."""
    text = SecretScanner().redact(value)[0]
    text = re.sub(r"(?i)(authorization|cookie|x-api-key)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    text = re.sub(r"(?i)(token|api[_-]?key|secret|password)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    text = _SENSITIVE_VALUE.sub("[REDACTED]", text)
    if re.search(r"(?i)(private prompt|mission prompt|source code|\.env|-----BEGIN)", text):
        return "[REDACTED]"
    return text[:500]


def _safe_log_line(line: str) -> str | None:
    """Allow structured event metadata only; drop unstructured/log-body text."""
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    safe: dict[str, Any] = {}
    for key in ("timestamp", "level", "module"):
        item = value.get(key)
        if isinstance(item, str) and len(item) <= 100:
            safe[key] = sanitize_text(item)
    event = value.get("event")
    if isinstance(event, str) and _SAFE_EVENT.fullmatch(event) and not _SECRET_KEY.search(event):
        # Event names are retained; arbitrary message bodies are not.
        safe["event"] = sanitize_text(event)
    context = value.get("context")
    if isinstance(context, dict):
        safe_context: dict[str, str | int | float | bool] = {}
        for key, item in context.items():
            key_text = str(key).lower()
            if key_text not in _SAFE_CONTEXT_KEYS or _SECRET_KEY.search(key_text):
                continue
            if isinstance(item, (str, int, float, bool)):
                normalized = sanitize_text(str(item)) if isinstance(item, str) else item
                if isinstance(normalized, (str, int, float, bool)):
                    safe_context[key_text] = normalized
        if safe_context:
            safe["context"] = safe_context
    if "timestamp" not in safe or "level" not in safe or "module" not in safe:
        return None
    return json.dumps(safe, sort_keys=True)


class DiagnosticsCollector:
    """Build a conservative diagnostics archive from explicitly supplied data."""

    def __init__(self, db: Database, *, started_monotonic: float | None = None) -> None:
        self.db = db
        self.started_monotonic = started_monotonic if started_monotonic is not None else time.monotonic()

    async def collect(
        self,
        *,
        providers: list[dict[str, Any]] | None = None,
        runtime_bindings: list[dict[str, Any]] | None = None,
        logs: list[str] | None = None,
        node_version: str | None = None,
    ) -> dict[str, Any]:
        tables = await self._tables()
        counts = await self._counts(tables)
        pragmas = await self._pragmas()
        return {
            "metadata": {
                "app_version": f"{__version__}-rc.1",
                "os": platform.system(),
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "python_version": platform.python_version(),
                "node_version": sanitize_text(node_version) if node_version else None,
                "applied_migrations": await self._migrations(),
                "memory_usage_bytes": self._memory_usage(),
                "uptime_seconds": max(0, int(time.monotonic() - self.started_monotonic)),
            },
            "providers": self._safe_providers(providers or []),
            "runtime_bindings": self._safe_bindings(runtime_bindings or []),
            "database_health": {
                "file_size_bytes": self.db.db_path.stat().st_size if self.db.db_path.exists() else 0,
                "pragmas": pragmas,
                "tables_count": len(tables),
                "records_summary": counts,
            },
            "logs_sanitized": self._safe_logs(logs or []),
        }

    async def export(self, output_path: Path | str, **data: Any) -> Path:
        report = await self.collect(**data)
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for key, filename in (
                    ("metadata", "metadata.json"),
                    ("providers", "providers.json"),
                    ("runtime_bindings", "runtime_bindings.json"),
                    ("database_health", "database_health.json"),
                ):
                    archive.writestr(filename, json.dumps(report[key], sort_keys=True, indent=2))
                archive.writestr("logs_sanitized.log", "\n".join(report["logs_sanitized"]) + "\n")
            os.replace(temporary, destination)
            return destination
        finally:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)

    async def _tables(self) -> list[str]:
        rows = await self.db.fetch_all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return [str(row["name"]) for row in rows]

    async def _counts(self, tables: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in tables:
            if table == "schema_migrations":
                continue
            # Table names come from sqlite_master and are identifier-quoted.
            row = await self.db.fetch_one(f'SELECT COUNT(*) AS n FROM "{table.replace(chr(34), chr(34) * 2)}"')
            counts[table] = int(row["n"]) if row else 0
        return counts

    async def _migrations(self) -> list[int]:
        tables = await self._tables()
        if "schema_migrations" not in tables:
            return []
        rows = await self.db.fetch_all("SELECT version FROM schema_migrations ORDER BY version")
        return [int(row["version"]) for row in rows if int(row["version"]) <= 21]

    async def _pragmas(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for pragma in ("integrity_check", "foreign_keys", "journal_mode", "user_version", "page_count", "freelist_count"):
            row = await self.db.fetch_one(f"PRAGMA {pragma}")
            result[pragma] = row[0] if row is not None else None
        return result

    def _memory_usage(self) -> int | None:
        try:
            import resource

            value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return value * (1024 if sys.platform != "darwin" else 1)
        except (ImportError, OSError, ValueError):
            return None

    @staticmethod
    def _safe_providers(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for provider in providers:
            name = provider.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", name):
                continue
            safe: dict[str, Any] = {"name": name}
            for key in ("available", "version"):
                value = provider.get(key)
                if isinstance(value, bool):
                    safe[key] = value
                elif key == "version" and isinstance(value, str) and len(value) <= 80:
                    safe[key] = sanitize_text(value)
            result.append(safe)
        return result

    @staticmethod
    def _safe_bindings(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for binding in bindings:
            safe: dict[str, Any] = {}
            for key in ("provider", "health", "configured_capacity", "observed_capacity", "reserved_slots"):
                value = binding.get(key)
                if isinstance(value, (str, int, float, bool)):
                    safe[key] = sanitize_text(value) if isinstance(value, str) else value
            branch = binding.get("target_branch")
            if isinstance(branch, str) and _SAFE_BRANCH.fullmatch(branch) and not _SENSITIVE_VALUE.search(branch):
                safe["target_branch"] = branch
            if safe:
                result.append(safe)
        return result

    @staticmethod
    def _safe_logs(logs: list[str]) -> list[str]:
        sanitized = [_safe_log_line(line) for line in logs[-500:]]
        return [line for line in sanitized if line is not None]


async def diagnose_recovery(
    db: Database,
    *,
    backup_path: Path | str | None = None,
    backup_dir: Path | str | None = None,
    current_schema_version: int = 21,
) -> list[RecoveryIssue]:
    """Return actionable, non-sensitive indicators without mutating files."""
    issues: list[RecoveryIssue] = []
    if not await asyncio.to_thread(db.db_path.exists):
        issues.append(RecoveryIssue(code="database_missing", message="Active database file is missing", path=str(db.db_path)))
    else:
        try:
            row = await db.fetch_one("PRAGMA integrity_check")
        except DatabaseError:
            row = None
        if row is None or row[0] != "ok":
            issues.append(RecoveryIssue(code="database_corrupt", message="SQLite integrity check failed", path=str(db.db_path)))
    if backup_path is not None and not await asyncio.to_thread(Path(backup_path).is_file):
        issues.append(RecoveryIssue(code="backup_missing", message="Requested backup file is missing", path=str(backup_path)))
    if backup_dir is not None:
        root = Path(backup_dir)
        issues.extend(await asyncio.to_thread(_inspect_backup_dir, root, current_schema_version))
    interrupted_restores = await asyncio.to_thread(list, db.db_path.parent.glob(f".{db.db_path.name}.restore-*.tmp"))
    for interrupted in interrupted_restores:
        issues.append(RecoveryIssue(code="restore_interrupted", message="An incomplete restore artifact was found", path=str(interrupted)))
    return issues


def _inspect_backup_dir(root: Path, current_schema_version: int) -> list[RecoveryIssue]:
    issues: list[RecoveryIssue] = []
    if not root.exists():
        return issues
    for interrupted in root.glob(".*.tmp"):
        issues.append(RecoveryIssue(code="backup_interrupted", message="An incomplete backup artifact was found", path=str(interrupted)))
    for manifest_path in root.glob("bkp-*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidate = root / f"{manifest.get('backup_id', '')}.db"
            if not candidate.is_file():
                issues.append(RecoveryIssue(code="backup_missing", message="Backup manifest has no database file", path=str(candidate)))
            elif int(manifest.get("schema_version", current_schema_version + 1)) > current_schema_version:
                issues.append(RecoveryIssue(code="schema_incompatible", message="Backup schema is newer than supported", path=str(manifest_path)))
            elif _file_sha256(candidate) != manifest.get("sha256"):
                issues.append(RecoveryIssue(code="checksum_invalid", message="Backup checksum does not match its manifest", path=str(candidate)))
        except (OSError, ValueError, TypeError):
            issues.append(RecoveryIssue(code="manifest_invalid", message="Backup manifest is unreadable or invalid", path=str(manifest_path)))
    return issues


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
