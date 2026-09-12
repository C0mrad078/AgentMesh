from __future__ import annotations

from pathlib import Path

from core.providers.base import ToolCallRequest
from core.tools.tool_schemas import ALL_TOOL_SCHEMAS, ToolExecutor


def _call(name: str, **arguments) -> ToolCallRequest:
    return ToolCallRequest(id="call_1", name=name, arguments=arguments)


async def test_read_file_succeeds_when_permitted(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    executor = ToolExecutor(tmp_path)
    result, duration = await executor.execute(_call("ReadFile", path="a.txt"), allowed_tools=frozenset({"ReadFile"}))
    assert result.error is None
    assert result.output == "hello"
    assert duration >= 0


async def test_tool_denied_when_not_in_allowed_set(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("ReadFile", path="a.txt"), allowed_tools=frozenset({"GitStatus"}))
    assert result.error is not None
    assert "not permitted" in result.error


async def test_unknown_tool_returns_error_not_exception(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(
        _call("DeleteEverything"), allowed_tools=frozenset({"DeleteEverything"})
    )
    assert result.error is not None
    assert "Unknown tool" in result.error


async def test_read_file_path_traversal_returns_error_not_exception(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(
        _call("ReadFile", path="../../etc/passwd"), allowed_tools=frozenset({"ReadFile"})
    )
    assert result.error is not None


async def test_read_file_missing_required_argument(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("ReadFile"), allowed_tools=frozenset({"ReadFile"}))
    assert result.error is not None


async def test_list_files_defaults_to_workspace_root(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("ListFiles"), allowed_tools=frozenset({"ListFiles"}))
    assert result.error is None
    assert any(entry["name"] == "a.txt" for entry in result.output)


async def test_git_status_on_non_repo_returns_error(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("GitStatus"), allowed_tools=frozenset({"GitStatus"}))
    # Not a git repo: git itself returns a non-zero/failure result, which our
    # GitTool surfaces as a successful tool call carrying a failed RunResult
    # (not a raised exception) -- either way, no crash.
    assert result.error is None
    assert result.output["success"] is False


async def test_write_file_succeeds_when_permitted(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(
        _call("WriteFile", path="out.txt", content="hi"), allowed_tools=frozenset({"WriteFile"})
    )
    assert result.error is None
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hi"


async def test_write_file_denied_without_permission(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(
        _call("WriteFile", path="out.txt", content="hi"), allowed_tools=frozenset({"ReadFile"})
    )
    assert result.error is not None
    assert not (tmp_path / "out.txt").exists()


def test_all_tool_schemas_have_names_and_descriptions() -> None:
    for name, schema in ALL_TOOL_SCHEMAS.items():
        assert schema.name == name
        assert schema.description
        assert isinstance(schema.parameters, dict)
