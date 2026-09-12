"""The tool catalog agents can call, and the dispatcher that actually runs
one.

Flow (see module docstring in `core.orchestrator.executor` for where this
is invoked from):

    Agent's AIResponse.tool_calls
        -> permission check (agent.tools)
        -> JSON-schema validation of arguments
        -> execute against the real, sandboxed tool
        -> ToolCallResult fed back to the model as a new message

Every tool name here maps 1:1 to a method on the safe tool wrappers from
Stage 1 (`FilesystemTool`, `GitTool`) or Stage 2 (`SearchTool`,
`CommandPlanner`) -- there is no generic "run this" tool.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.providers.base import ToolCallRequest, ToolCallResult, ToolSchema
from core.tools.command_planner import CommandPlanner, ProjectAction
from core.tools.filesystem_tool import FilesystemTool
from core.tools.git_tool import GitTool
from core.tools.search_tool import SearchTool
from core.utils.errors import NotFoundError, OrchestratorError, ToolDeniedError
from core.utils.logging import get_logger

logger = get_logger("tools.executor")

READ_FILE = ToolSchema(
    name="ReadFile",
    description="Read the contents of a text file within the project workspace.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path relative to the project root."}},
        "required": ["path"],
    },
)

LIST_FILES = ToolSchema(
    name="ListFiles",
    description="List files and directories at a path within the project workspace.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "default": "."}},
    },
)

SEARCH_FILES = ToolSchema(
    name="SearchFiles",
    description="Search file contents for a text pattern within the project workspace.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)

WRITE_FILE = ToolSchema(
    name="WriteFile",
    description="Write (create or overwrite) a text file within the project workspace.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the project root."},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
)

GIT_STATUS = ToolSchema(
    name="GitStatus",
    description="Show the git status of the project workspace.",
    parameters={"type": "object", "properties": {}},
)

GIT_DIFF = ToolSchema(
    name="GitDiff",
    description="Show the git diff of the project workspace.",
    parameters={
        "type": "object",
        "properties": {"staged": {"type": "boolean", "default": False}},
    },
)

RUN_TEST = ToolSchema(
    name="RunTest",
    description="Run the project's test suite, auto-detected for its stack.",
    parameters={"type": "object", "properties": {}},
)

RUN_BUILD = ToolSchema(
    name="RunBuild",
    description="Run the project's build, auto-detected for its stack.",
    parameters={"type": "object", "properties": {}},
)

ALL_TOOL_SCHEMAS: dict[str, ToolSchema] = {
    tool.name: tool
    for tool in (
        READ_FILE, LIST_FILES, SEARCH_FILES, WRITE_FILE, GIT_STATUS, GIT_DIFF, RUN_TEST, RUN_BUILD,
    )
}


class ToolExecutor:
    """Dispatches a validated `ToolCallRequest` to the real, sandboxed tool.

    Constructed per-execution with the workspace root the call is scoped
    to. Never raises for a tool-level failure (permission denied, bad
    arguments, tool error) -- it always returns a `ToolCallResult`, setting
    `.error` instead, so the agent's tool-use loop can react to the failure
    the same way a real tool-use API would (the model sees the error and
    can try something else) rather than the whole step blowing up.
    """

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        self._filesystem = FilesystemTool(workspace_root)
        self._git = GitTool(workspace_root)
        self._search = SearchTool(workspace_root)
        self._commands = CommandPlanner(workspace_root)

    async def execute(
        self, call: ToolCallRequest, *, allowed_tools: frozenset[str]
    ) -> tuple[ToolCallResult, float]:
        """Returns (result, duration_seconds)."""
        start = time.monotonic()

        if call.name not in ALL_TOOL_SCHEMAS:
            return self._error_result(call, f"Unknown tool '{call.name}'."), 0.0
        if call.name not in allowed_tools:
            return (
                self._error_result(call, f"Agent is not permitted to use tool '{call.name}'."),
                0.0,
            )

        try:
            output = await self._dispatch(call)
            return ToolCallResult(id=call.id, name=call.name, output=output), time.monotonic() - start
        except OrchestratorError as exc:
            return self._error_result(call, exc.message), time.monotonic() - start
        except Exception as exc:  # noqa: BLE001 - tool failures must never crash the step
            logger.error(
                "tool_execution_failed", extra={"context": {"tool": call.name, "type": type(exc).__name__}}
            )
            return self._error_result(call, "The tool failed unexpectedly."), time.monotonic() - start

    def _error_result(self, call: ToolCallRequest, message: str) -> ToolCallResult:
        return ToolCallResult(id=call.id, name=call.name, output=None, error=message)

    async def _dispatch(self, call: ToolCallRequest) -> Any:
        args = call.arguments

        if call.name == "ReadFile":
            path = _require_str(args, "path")
            return self._filesystem.read_file(path)

        if call.name == "ListFiles":
            path = args.get("path", ".")
            entries = self._filesystem.list_dir(path)
            return [entry.__dict__ for entry in entries]

        if call.name == "SearchFiles":
            query = _require_str(args, "query")
            matches = await self._search.search(query)
            return [m.__dict__ for m in matches]

        if call.name == "WriteFile":
            path = _require_str(args, "path")
            content = args.get("content")
            if not isinstance(content, str):
                raise ToolDeniedError("Tool argument 'content' is required and must be a string.")
            self._filesystem.write_file(path, content)
            return {"path": path, "bytes_written": len(content.encode("utf-8"))}

        if call.name == "GitStatus":
            result = await self._git.status()
            return result.__dict__

        if call.name == "GitDiff":
            staged = bool(args.get("staged", False))
            result = await self._git.diff(staged=staged)
            return result.__dict__

        if call.name == "RunTest":
            result = await self._commands.run(ProjectAction.RUN_TESTS)
            return result.__dict__

        if call.name == "RunBuild":
            result = await self._commands.run(ProjectAction.RUN_BUILD)
            return result.__dict__

        raise NotFoundError(f"Unhandled tool '{call.name}'.")


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ToolDeniedError(f"Tool argument '{key}' is required and must be a non-empty string.")
    return value
