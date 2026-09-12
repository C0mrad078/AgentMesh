"""Safe, workspace-confined filesystem operations.

Every method takes a path relative to the tool's workspace root and resolves
it through `core.tools.path_guard.resolve_safe_path` before touching disk.
There is no method that accepts or returns an absolute, caller-supplied path
without going through that guard.

Writes that touch an *existing* file (`write_file` overwriting content,
`delete_file`) are atomic and back the previous content up first:

    write temp file (same directory, so the final rename stays on one
    filesystem) -> fsync -> os.replace() over the original

`os.replace` is atomic on both POSIX and Windows, so a crash mid-write
either leaves the original file completely untouched or the new content
fully in place -- never a half-written file. Exactly one backup
(`<name>.orchestrator-backup`) is kept per file, overwritten each time --
this is a safety net for the current operation, not version history (that
is what Git is for), so it deliberately does not accumulate.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.tools.base import Tool
from core.tools.path_guard import resolve_safe_path
from core.utils.errors import AlreadyExistsError, NotFoundError, PathTraversalError, ToolDeniedError

_MAX_READ_BYTES = 5 * 1024 * 1024  # 5 MiB safety cap for a single read
_MAX_WRITE_BYTES = 2 * 1024 * 1024  # 2 MiB safety cap for a single write
_BACKUP_SUFFIX = ".orchestrator-backup"


@dataclass(frozen=True)
class FileEntry:
    name: str
    path: str
    is_dir: bool
    size: int | None


@dataclass(frozen=True)
class FileMetadata:
    path: str
    exists: bool
    is_dir: bool
    is_file: bool
    size: int | None
    modified_at: float | None


@dataclass(frozen=True)
class FileOpResult:
    path: str
    backup_path: str | None = None


def _atomic_write(target: Path, encoded: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _backup(target: Path) -> Path | None:
    if not target.exists():
        return None
    backup_path = target.with_name(target.name + _BACKUP_SUFFIX)
    shutil.copy2(target, backup_path)
    return backup_path


class FilesystemTool(Tool):
    name = "filesystem"

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)

    def list_dir(self, relative_path: str = ".") -> list[FileEntry]:
        target = resolve_safe_path(self.workspace_root, relative_path)
        if not target.exists():
            raise NotFoundError(f"Directory '{relative_path}' does not exist.")
        if not target.is_dir():
            raise NotFoundError(f"'{relative_path}' is not a directory.")

        entries: list[FileEntry] = []
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            rel = child.relative_to(self.workspace_root).as_posix()
            entries.append(
                FileEntry(
                    name=child.name,
                    path=rel,
                    is_dir=child.is_dir(),
                    size=child.stat().st_size if child.is_file() else None,
                )
            )
        return entries

    def read_file(self, relative_path: str, *, max_bytes: int = _MAX_READ_BYTES) -> str:
        target = resolve_safe_path(self.workspace_root, relative_path)
        if not target.exists() or not target.is_file():
            raise NotFoundError(f"File '{relative_path}' does not exist.")

        # Read at most `max_bytes + 1` bytes directly from the file handle
        # rather than loading the whole file first -- an arbitrarily large
        # file must never be fully read into memory just to reject it.
        with target.open("rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(
                f"File '{relative_path}' exceeds the maximum readable size of {max_bytes} bytes."
            )
        return data.decode("utf-8", errors="replace")

    def write_file(
        self, relative_path: str, content: str, *, max_bytes: int = _MAX_WRITE_BYTES
    ) -> FileOpResult:
        """Create or atomically overwrite a file. An existing file is
        backed up first (see module docstring)."""
        encoded = content.encode("utf-8")
        if len(encoded) > max_bytes:
            raise ToolDeniedError(
                f"Refusing to write '{relative_path}': {len(encoded)} bytes exceeds the "
                f"maximum of {max_bytes} bytes for a single write.",
            )
        target = resolve_safe_path(self.workspace_root, relative_path)
        backup = _backup(target)
        _atomic_write(target, encoded)
        return FileOpResult(
            path=relative_path,
            backup_path=backup.relative_to(self.workspace_root).as_posix() if backup else None,
        )

    def create_file(self, relative_path: str, content: str = "", *, max_bytes: int = _MAX_WRITE_BYTES) -> FileOpResult:
        """Like `write_file`, but refuses to overwrite an existing file --
        distinct risk/intent from `write_file` (see `core.security.permissions`)."""
        target = resolve_safe_path(self.workspace_root, relative_path)
        if target.exists():
            raise AlreadyExistsError(f"'{relative_path}' already exists; use WriteFile to overwrite it.")
        encoded = content.encode("utf-8")
        if len(encoded) > max_bytes:
            raise ToolDeniedError(
                f"Refusing to create '{relative_path}': {len(encoded)} bytes exceeds the "
                f"maximum of {max_bytes} bytes.",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, encoded)
        return FileOpResult(path=relative_path)

    def delete_file(self, relative_path: str) -> FileOpResult:
        """Backs the file up (`<name>.orchestrator-backup`) before removing
        it -- deletion is HIGH risk (see `core.security.permissions
        .OPERATION_RISK`) precisely because it is hard to undo; this makes
        the most recent version recoverable for one operation's worth of
        safety margin."""
        target = resolve_safe_path(self.workspace_root, relative_path)
        if not target.exists() or not target.is_file():
            raise NotFoundError(f"File '{relative_path}' does not exist.")
        backup = _backup(target)
        target.unlink()
        return FileOpResult(
            path=relative_path,
            backup_path=backup.relative_to(self.workspace_root).as_posix() if backup else None,
        )

    def move_file(self, relative_source: str, relative_destination: str) -> FileOpResult:
        source = resolve_safe_path(self.workspace_root, relative_source)
        destination = resolve_safe_path(self.workspace_root, relative_destination)
        if not source.exists():
            raise NotFoundError(f"'{relative_source}' does not exist.")
        if destination.exists():
            raise AlreadyExistsError(f"'{relative_destination}' already exists.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        return FileOpResult(path=relative_destination)

    def copy_file(self, relative_source: str, relative_destination: str) -> FileOpResult:
        source = resolve_safe_path(self.workspace_root, relative_source)
        destination = resolve_safe_path(self.workspace_root, relative_destination)
        if not source.exists() or not source.is_file():
            raise NotFoundError(f"'{relative_source}' does not exist.")
        if destination.exists():
            raise AlreadyExistsError(f"'{relative_destination}' already exists.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return FileOpResult(path=relative_destination)

    def exists(self, relative_path: str) -> bool:
        try:
            target = resolve_safe_path(self.workspace_root, relative_path)
        except PathTraversalError:
            return False
        return target.exists()

    def metadata(self, relative_path: str) -> FileMetadata:
        target = resolve_safe_path(self.workspace_root, relative_path)
        if not target.exists():
            return FileMetadata(
                path=relative_path, exists=False, is_dir=False, is_file=False, size=None,
                modified_at=None,
            )
        stat = target.stat()
        return FileMetadata(
            path=relative_path,
            exists=True,
            is_dir=target.is_dir(),
            is_file=target.is_file(),
            size=stat.st_size if target.is_file() else None,
            modified_at=stat.st_mtime,
        )
