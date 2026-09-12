"""Safe, workspace-confined filesystem operations.

Every method takes a path relative to the tool's workspace root and resolves
it through `core.tools.path_guard.resolve_safe_path` before touching disk.
There is no method that accepts or returns an absolute, caller-supplied path
without going through that guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.tools.base import Tool
from core.tools.path_guard import resolve_safe_path
from core.utils.errors import NotFoundError, ToolDeniedError

_MAX_READ_BYTES = 5 * 1024 * 1024  # 5 MiB safety cap for a single read
_MAX_WRITE_BYTES = 2 * 1024 * 1024  # 2 MiB safety cap for a single write


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
    ) -> None:
        encoded = content.encode("utf-8")
        if len(encoded) > max_bytes:
            raise ToolDeniedError(
                f"Refusing to write '{relative_path}': {len(encoded)} bytes exceeds the "
                f"maximum of {max_bytes} bytes for a single write.",
            )
        target = resolve_safe_path(self.workspace_root, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)

    def exists(self, relative_path: str) -> bool:
        try:
            target = resolve_safe_path(self.workspace_root, relative_path)
        except Exception:
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
