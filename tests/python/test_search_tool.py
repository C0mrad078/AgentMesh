from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.tools.search_tool import SearchMatch, SearchTool
from core.utils.shell_runner import RunResult


async def test_search_finds_matching_lines(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def login():\n    check_password()\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def unrelated():\n    pass\n", encoding="utf-8")
    tool = SearchTool(tmp_path)

    matches = await tool.search("check_password")
    assert any(m.path == "a.py" and m.line == 2 for m in matches)
    assert not any(m.path == "b.py" for m in matches)


async def test_search_empty_query_returns_no_matches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("content", encoding="utf-8")
    tool = SearchTool(tmp_path)
    assert await tool.search("   ") == []


async def test_search_respects_ignored_paths(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("needle", encoding="utf-8")
    (tmp_path / "app.js").write_text("needle", encoding="utf-8")
    tool = SearchTool(tmp_path)
    matches = await tool.search("needle")
    assert any(m.path == "app.js" for m in matches)
    assert not any("node_modules" in m.path for m in matches)


async def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello world", encoding="utf-8")
    tool = SearchTool(tmp_path)
    assert await tool.search("does-not-exist-anywhere") == []


async def test_search_uses_ripgrep_when_available_and_parses_its_output(tmp_path: Path) -> None:
    tool = SearchTool(tmp_path)
    fake_result = RunResult(
        success=True, stdout="src/auth.py:3:def check_password():\n", stderr="", returncode=0
    )
    with (
        patch("core.tools.search_tool.shutil.which", return_value="/usr/bin/rg"),
        patch.object(tool._runner, "run", new=AsyncMock(return_value=fake_result)) as mock_run,
    ):
        matches = await tool.search("check_password")

    assert matches == [SearchMatch(path="src/auth.py", line=3, text="def check_password():")]
    called_argv = mock_run.call_args.args[0]
    assert called_argv[0] == "rg"
    assert "check_password" in called_argv
    assert "--ignore-case" in called_argv
    assert "--glob=!node_modules/" in called_argv


async def test_search_ripgrep_path_strips_leading_dot_slash(tmp_path: Path) -> None:
    # `rg` run against `.` prints paths prefixed with `./`; the fallback
    # scanner never does, so ripgrep's output is normalized to match.
    tool = SearchTool(tmp_path)
    fake_result = RunResult(success=True, stdout="./app.js:1:const TODO = 1;\n", stderr="", returncode=0)
    with (
        patch("core.tools.search_tool.shutil.which", return_value="/usr/bin/rg"),
        patch.object(tool._runner, "run", new=AsyncMock(return_value=fake_result)),
    ):
        matches = await tool.search("todo")

    assert matches == [SearchMatch(path="app.js", line=1, text="const TODO = 1;")]
