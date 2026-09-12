from __future__ import annotations

from pathlib import Path

from core.agents.models import Agent, AgentPermissions
from core.providers.base import ToolCallRequest
from core.tools.tool_schemas import ALL_TOOL_SCHEMAS, ToolExecutor


def _call(name: str, **arguments) -> ToolCallRequest:
    return ToolCallRequest(id="call_1", name=name, arguments=arguments)


def _agent(tools: list[str], **permission_overrides) -> Agent:
    defaults = {
        "can_read_files": True, "can_write_files": True, "can_run_git": True, "can_run_terminal": True,
    }
    defaults.update(permission_overrides)
    return Agent(id="agent_test", name="Test Agent", provider="mock", tools=tools, permissions=AgentPermissions(**defaults))


async def test_read_file_succeeds_when_permitted(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    executor = ToolExecutor(tmp_path)
    result, duration = await executor.execute(_call("ReadFile", path="a.txt"), agent=_agent(["ReadFile"]))
    assert result.error is None
    assert result.output == "hello"
    assert duration >= 0


async def test_tool_denied_when_not_in_allowed_set(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    executor = ToolExecutor(tmp_path)
    # WriteFile is MEDIUM risk and always requires explicit listing in
    # `agent.tools` -- unlike the LOW-risk read-only tools, which the
    # capability flag alone implies (see `core.security.permissions
    # ._IMPLIED_BY_CAPABILITY_ALONE`).
    result, _ = await executor.execute(_call("WriteFile", path="a.txt", content="x"), agent=_agent(["GitStatus"]))
    assert result.error is not None
    assert "Permission denied" in result.error


async def test_unknown_tool_returns_error_not_exception(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("DeleteEverything"), agent=_agent(["DeleteEverything"]))
    assert result.error is not None
    assert "Unknown tool" in result.error


async def test_read_file_path_traversal_returns_error_not_exception(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("ReadFile", path="../../etc/passwd"), agent=_agent(["ReadFile"]))
    assert result.error is not None


async def test_read_file_missing_required_argument(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("ReadFile"), agent=_agent(["ReadFile"]))
    assert result.error is not None


async def test_list_files_defaults_to_workspace_root(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("ListFiles"), agent=_agent(["ListFiles"]))
    assert result.error is None
    assert any(entry["name"] == "a.txt" for entry in result.output)


async def test_git_status_on_non_repo_returns_error(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("GitStatus"), agent=_agent(["GitStatus"]))
    # Not a git repo: git itself returns a non-zero/failure result, which our
    # GitTool surfaces as a successful tool call carrying a failed RunResult
    # (not a raised exception) -- either way, no crash.
    assert result.error is None
    assert result.output["success"] is False


async def test_write_file_succeeds_when_permitted(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(
        _call("WriteFile", path="out.txt", content="hi"), agent=_agent(["WriteFile"])
    )
    assert result.error is None
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hi"


async def test_write_file_denied_without_permission(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(
        _call("WriteFile", path="out.txt", content="hi"), agent=_agent(["ReadFile"], can_write_files=False)
    )
    assert result.error is not None
    assert not (tmp_path / "out.txt").exists()


async def test_delete_file_requires_confirmation_when_not_pre_authorized(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("DeleteFile", path="a.txt"), agent=_agent(["DeleteFile"]))
    assert result.error is not None
    assert "confirmation" in result.error
    assert (tmp_path / "a.txt").exists()


async def test_delete_file_succeeds_when_pre_authorized(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    executor = ToolExecutor(tmp_path, pre_authorized_operations=frozenset({"DeleteFile"}))
    result, _ = await executor.execute(_call("DeleteFile", path="a.txt"), agent=_agent(["DeleteFile"]))
    assert result.error is None
    assert not (tmp_path / "a.txt").exists()


async def test_git_push_requires_confirmation_when_not_pre_authorized(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path)
    result, _ = await executor.execute(_call("GitPush"), agent=_agent(["GitPush"]))
    assert result.error is not None
    assert "confirmation" in result.error


async def test_git_reset_hard_denied_when_not_in_agent_tools(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path, pre_authorized_operations=frozenset({"GitResetHard"}))
    result, _ = await executor.execute(_call("GitResetHard"), agent=_agent(["ReadFile"]))
    assert result.error is not None
    assert "Permission denied" in result.error


def test_all_tool_schemas_have_names_and_descriptions() -> None:
    for name, schema in ALL_TOOL_SCHEMAS.items():
        assert schema.name == name
        assert schema.description
        assert isinstance(schema.parameters, dict)
