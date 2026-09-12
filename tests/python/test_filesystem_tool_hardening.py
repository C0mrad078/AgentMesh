"""Stage 4 filesystem hardening: atomic writes, backup-before-overwrite,
and the new typed Create/Delete/Move/Copy operations."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.tools.filesystem_tool import FilesystemTool
from core.utils.errors import AlreadyExistsError, NotFoundError, ToolDeniedError


def test_write_file_overwriting_an_existing_file_creates_a_backup(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    tool.write_file("a.txt", "original")
    result = tool.write_file("a.txt", "changed")

    assert (tmp_path / "a.txt").read_text() == "changed"
    assert result.backup_path == "a.txt.orchestrator-backup"
    assert (tmp_path / "a.txt.orchestrator-backup").read_text() == "original"


def test_write_file_first_time_creates_no_backup(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    result = tool.write_file("new.txt", "hello")
    assert result.backup_path is None
    assert not (tmp_path / "new.txt.orchestrator-backup").exists()


def test_backup_is_overwritten_not_accumulated(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    tool.write_file("a.txt", "v1")
    tool.write_file("a.txt", "v2")
    tool.write_file("a.txt", "v3")

    assert (tmp_path / "a.txt").read_text() == "v3"
    assert (tmp_path / "a.txt.orchestrator-backup").read_text() == "v2"
    backups = list(tmp_path.glob("a.txt*backup*"))
    assert len(backups) == 1


def test_write_file_no_original_left_behind_on_crash_mid_write(tmp_path: Path, monkeypatch) -> None:
    tool = FilesystemTool(tmp_path)
    tool.write_file("a.txt", "original")

    import core.tools.filesystem_tool as fs_module

    def _boom(*args, **kwargs):
        raise OSError("simulated crash during write")

    monkeypatch.setattr(fs_module.os, "replace", _boom)
    with pytest.raises(OSError):
        tool.write_file("a.txt", "corrupted")

    # The original file must be untouched -- os.replace() never ran.
    assert (tmp_path / "a.txt").read_text() == "original"
    # No leftover temp file.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".a.txt.")]
    assert leftovers == []


def test_create_file_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    tool.create_file("a.txt", "one")
    with pytest.raises(AlreadyExistsError):
        tool.create_file("a.txt", "two")
    assert (tmp_path / "a.txt").read_text() == "one"


def test_delete_file_backs_up_before_removing(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    tool.write_file("a.txt", "content")
    result = tool.delete_file("a.txt")

    assert not (tmp_path / "a.txt").exists()
    assert result.backup_path == "a.txt.orchestrator-backup"
    assert (tmp_path / "a.txt.orchestrator-backup").read_text() == "content"


def test_delete_file_missing_raises_not_found(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    with pytest.raises(NotFoundError):
        tool.delete_file("missing.txt")


def test_move_file_relocates_content(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    tool.write_file("a.txt", "content")
    tool.move_file("a.txt", "sub/b.txt")

    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "sub" / "b.txt").read_text() == "content"


def test_move_file_refuses_to_overwrite_destination(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    tool.write_file("a.txt", "a")
    tool.write_file("b.txt", "b")
    with pytest.raises(AlreadyExistsError):
        tool.move_file("a.txt", "b.txt")


def test_copy_file_duplicates_content_and_keeps_the_original(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    tool.write_file("a.txt", "content")
    tool.copy_file("a.txt", "copy.txt")

    assert (tmp_path / "a.txt").read_text() == "content"
    assert (tmp_path / "copy.txt").read_text() == "content"


def test_move_and_copy_reject_path_traversal_on_either_side(tmp_path: Path) -> None:
    from core.utils.errors import PathTraversalError

    tool = FilesystemTool(tmp_path)
    tool.write_file("a.txt", "content")
    with pytest.raises(PathTraversalError):
        tool.move_file("a.txt", "../escape.txt")
    with pytest.raises(PathTraversalError):
        tool.copy_file("../outside.txt", "b.txt")


def test_create_file_rejects_oversized_content(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)
    with pytest.raises(ToolDeniedError):
        tool.create_file("big.txt", "x" * 100, max_bytes=10)
