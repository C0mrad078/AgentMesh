from __future__ import annotations

from pathlib import Path

import pytest
from core.tools.filesystem_tool import FilesystemTool
from core.tools.path_guard import resolve_safe_path
from core.utils.errors import PathTraversalError


def test_valid_relative_path_resolves(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    resolved = resolve_safe_path(tmp_path, "sub")
    assert resolved == (tmp_path / "sub").resolve()


def test_dot_dot_traversal_denied(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_safe_path(tmp_path, "../outside")


def test_absolute_path_escape_denied(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_safe_path(tmp_path, "/etc/passwd")


def test_nested_traversal_denied(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    with pytest.raises(PathTraversalError):
        resolve_safe_path(tmp_path, "a/b/../../../etc")


def test_symlink_escape_denied(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "escape_link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not supported in this environment")
    with pytest.raises(PathTraversalError):
        resolve_safe_path(tmp_path, "escape_link/../../outside_target")


def test_filesystem_tool_list_and_read(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    tool = FilesystemTool(tmp_path)
    entries = tool.list_dir(".")
    assert any(e.name == "file.txt" for e in entries)
    assert tool.read_file("file.txt") == "hello"
    assert tool.exists("file.txt") is True
    assert tool.exists("../outside") is False


def test_filesystem_tool_metadata_missing_file(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    meta = tool.metadata("missing.txt")
    assert meta.exists is False


def test_filesystem_tool_rejects_files_over_the_size_cap(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_bytes(b"x" * 100)
    tool = FilesystemTool(tmp_path)
    with pytest.raises(ValueError):
        tool.read_file("big.txt", max_bytes=10)
