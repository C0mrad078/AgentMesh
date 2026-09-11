from __future__ import annotations

from pathlib import Path

from core.tools.git_tool import GitTool
from core.tools.terminal_tool import TerminalCommand, TerminalTool

_REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_git_tool_status_on_real_repo() -> None:
    tool = GitTool(_REPO_ROOT)
    assert await tool.is_repository() is True
    result = await tool.status()
    assert result.success is True


async def test_git_tool_diff_on_real_repo() -> None:
    tool = GitTool(_REPO_ROOT)
    result = await tool.diff()
    assert result.success is True


async def test_git_tool_rejects_missing_workspace(tmp_path: Path) -> None:
    from core.utils.errors import ToolDeniedError

    tool = GitTool(tmp_path / "does-not-exist")
    try:
        await tool.status()
        raised = False
    except ToolDeniedError:
        raised = True
    assert raised


async def test_terminal_tool_python_version(tmp_path: Path) -> None:
    tool = TerminalTool(tmp_path)
    result = await tool.run(TerminalCommand.PYTHON_VERSION)
    assert result.success is True
    assert "Python" in result.stdout or "Python" in result.stderr


async def test_terminal_tool_working_directory(tmp_path: Path) -> None:
    tool = TerminalTool(tmp_path)
    result = await tool.run(TerminalCommand.WORKING_DIRECTORY)
    assert result.success is True
