from __future__ import annotations

from pathlib import Path

from core.tools.project_scanner import ProjectScanner


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login(): pass", encoding="utf-8")
    (tmp_path / "src" / "utils.py").write_text("def helper(): pass", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("noise", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo", encoding="utf-8")
    return tmp_path


def test_scan_respects_default_ignores(tmp_path: Path) -> None:
    _make_project(tmp_path)
    scanner = ProjectScanner(tmp_path)
    paths = {entry.path for entry in scanner.scan()}
    assert "src/auth.py" in paths
    assert not any(p.startswith("node_modules/") for p in paths)
    assert ".env" not in paths


def test_scan_respects_gitignore(tmp_path: Path) -> None:
    _make_project(tmp_path)
    (tmp_path / ".gitignore").write_text("*.md\n", encoding="utf-8")
    scanner = ProjectScanner(tmp_path)
    paths = {entry.path for entry in scanner.scan()}
    assert "README.md" not in paths
    assert "src/auth.py" in paths


def test_relevant_files_ranks_by_keyword_overlap(tmp_path: Path) -> None:
    _make_project(tmp_path)
    scanner = ProjectScanner(tmp_path)
    results = scanner.relevant_files(["auth"])
    assert any(entry.path == "src/auth.py" for entry in results)
    assert all("utils" not in entry.path for entry in results)


def test_relevant_files_with_no_matches_returns_empty(tmp_path: Path) -> None:
    _make_project(tmp_path)
    scanner = ProjectScanner(tmp_path)
    assert scanner.relevant_files(["nonexistentkeyword"]) == []


def test_scan_on_missing_workspace_returns_empty(tmp_path: Path) -> None:
    scanner = ProjectScanner(tmp_path / "does-not-exist")
    assert scanner.scan() == []
