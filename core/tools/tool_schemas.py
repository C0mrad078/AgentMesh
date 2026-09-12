"""The tool catalog agents can call, and the dispatcher that actually runs
one.

Flow (see module docstring in `core.orchestrator.executor` for where this
is invoked from):

    Agent's AIResponse.tool_calls
        -> core.security.permissions.PermissionEngine.evaluate()
           (capability flags + agent.tools allowlist + operation risk)
        -> JSON-schema validation of arguments
        -> execute against the real, sandboxed tool
        -> ToolCallResult fed back to the model as a new message

Every tool name here maps 1:1 to a method on the safe tool wrappers from
Stage 1 (`FilesystemTool`, `GitTool`) or Stage 2 (`SearchTool`,
`CommandPlanner`) -- there is no generic "run this" tool.

A HIGH/CRITICAL-risk operation (`DeleteFile`, `GitPush`, `GitResetHard`,
...) that is not in `pre_authorized_operations` comes back from the
Permission Engine as `require_confirmation`, which this dispatcher treats
as denied: there is no interactive confirmation dialog wired up yet (see
the Stage 4 report's limitations), so the honest behavior is to refuse
rather than silently proceed or silently block forever. `pre_authorized
_operations` is the seam a future confirmation UI hooks into -- it is
already threaded end-to-end from `Task.input["confirmed_operations"]`
(see `core.orchestrator.engine`), just not populated by any UI yet.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.agents.models import Agent
from core.providers.base import ToolCallRequest, ToolCallResult, ToolSchema
from core.security.permissions import PermissionAction, PermissionEngine, PermissionRequest
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
    parameters={"type": "object", "properties": {"path": {"type": "string", "default": "."}}},
)

GET_METADATA = ToolSchema(
    name="GetMetadata",
    description="Get size/type/modified-time metadata for a path within the project workspace.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)

SEARCH_FILES = ToolSchema(
    name="SearchFiles",
    description="Search file contents for a text pattern within the project workspace.",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
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

CREATE_FILE = ToolSchema(
    name="CreateFile",
    description="Create a new text file within the project workspace. Fails if it already exists.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string", "default": ""}},
        "required": ["path"],
    },
)

DELETE_FILE = ToolSchema(
    name="DeleteFile",
    description="Delete a file within the project workspace. High risk: requires confirmation.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)

MOVE_FILE = ToolSchema(
    name="MoveFile",
    description="Move/rename a file within the project workspace.",
    parameters={
        "type": "object",
        "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
        "required": ["source", "destination"],
    },
)

COPY_FILE = ToolSchema(
    name="CopyFile",
    description="Copy a file within the project workspace.",
    parameters={
        "type": "object",
        "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
        "required": ["source", "destination"],
    },
)

GIT_STATUS = ToolSchema(
    name="GitStatus", description="Show the git status of the project workspace.",
    parameters={"type": "object", "properties": {}},
)

GIT_DIFF = ToolSchema(
    name="GitDiff", description="Show the git diff of the project workspace.",
    parameters={"type": "object", "properties": {"staged": {"type": "boolean", "default": False}}},
)

GIT_LOG = ToolSchema(
    name="GitLog", description="Show recent commit history of the project workspace.",
    parameters={"type": "object", "properties": {"max_count": {"type": "integer", "default": 20}}},
)

GIT_SHOW = ToolSchema(
    name="GitShow", description="Show a specific git revision.",
    parameters={"type": "object", "properties": {"revision": {"type": "string"}}, "required": ["revision"]},
)

GIT_BRANCH_LIST = ToolSchema(
    name="GitBranchList", description="List local git branches.",
    parameters={"type": "object", "properties": {}},
)

GIT_ADD = ToolSchema(
    name="GitAdd", description="Stage files for commit.",
    parameters={
        "type": "object",
        "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
        "required": ["paths"],
    },
)

GIT_COMMIT = ToolSchema(
    name="GitCommit", description="Commit staged changes.",
    parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
)

GIT_CHECKOUT = ToolSchema(
    name="GitCheckout", description="Check out a branch or revision.",
    parameters={"type": "object", "properties": {"revision": {"type": "string"}}, "required": ["revision"]},
)

GIT_CREATE_BRANCH = ToolSchema(
    name="GitCreateBranch", description="Create and check out a new branch.",
    parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)

GIT_REVERT = ToolSchema(
    name="GitRevert", description="Revert a specific commit.",
    parameters={"type": "object", "properties": {"revision": {"type": "string"}}, "required": ["revision"]},
)

GIT_MERGE = ToolSchema(
    name="GitMerge", description="Merge a branch into the current branch. High risk.",
    parameters={"type": "object", "properties": {"revision": {"type": "string"}}, "required": ["revision"]},
)

GIT_PUSH = ToolSchema(
    name="GitPush", description="Push commits to a remote. High risk: requires confirmation.",
    parameters={
        "type": "object",
        "properties": {"remote": {"type": "string", "default": "origin"}, "branch": {"type": "string"}},
    },
)

GIT_FORCE_PUSH = ToolSchema(
    name="GitForcePush",
    description="Force-push (with lease) to a remote. Critical risk: requires confirmation.",
    parameters={
        "type": "object",
        "properties": {"remote": {"type": "string", "default": "origin"}, "branch": {"type": "string"}},
    },
)

GIT_RESET_HARD = ToolSchema(
    name="GitResetHard",
    description="Discard uncommitted changes and reset to a revision. Critical risk: requires confirmation.",
    parameters={"type": "object", "properties": {"revision": {"type": "string", "default": "HEAD"}}},
)

GIT_CLEAN_FD = ToolSchema(
    name="GitCleanFd",
    description="Remove untracked files and directories. Critical risk: requires confirmation.",
    parameters={"type": "object", "properties": {}},
)

GIT_BRANCH_DELETE = ToolSchema(
    name="GitBranchDelete", description="Delete a local branch. High risk: requires confirmation.",
    parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)

RUN_TEST = ToolSchema(
    name="RunTest", description="Run the project's test suite, auto-detected for its stack.",
    parameters={"type": "object", "properties": {}},
)

RUN_BUILD = ToolSchema(
    name="RunBuild", description="Run the project's build, auto-detected for its stack.",
    parameters={"type": "object", "properties": {}},
)

RUN_LINT = ToolSchema(
    name="RunLint", description="Run the project's linter, auto-detected for its stack.",
    parameters={"type": "object", "properties": {}},
)

RUN_TYPECHECK = ToolSchema(
    name="RunTypecheck", description="Run the project's type checker, auto-detected for its stack.",
    parameters={"type": "object", "properties": {}},
)

INSTALL_DEPENDENCIES = ToolSchema(
    name="InstallDependencies", description="Install the project's dependencies, auto-detected for its stack.",
    parameters={"type": "object", "properties": {}},
)

ALL_TOOL_SCHEMAS: dict[str, ToolSchema] = {
    tool.name: tool
    for tool in (
        READ_FILE, LIST_FILES, GET_METADATA, SEARCH_FILES, WRITE_FILE, CREATE_FILE, DELETE_FILE,
        MOVE_FILE, COPY_FILE, GIT_STATUS, GIT_DIFF, GIT_LOG, GIT_SHOW, GIT_BRANCH_LIST, GIT_ADD,
        GIT_COMMIT, GIT_CHECKOUT, GIT_CREATE_BRANCH, GIT_REVERT, GIT_MERGE, GIT_PUSH, GIT_FORCE_PUSH,
        GIT_RESET_HARD, GIT_CLEAN_FD, GIT_BRANCH_DELETE, RUN_TEST, RUN_BUILD, RUN_LINT, RUN_TYPECHECK,
        INSTALL_DEPENDENCIES,
    )
}

_ACTION_BY_TOOL: dict[str, ProjectAction] = {
    "RunTest": ProjectAction.RUN_TESTS,
    "RunBuild": ProjectAction.RUN_BUILD,
    "RunLint": ProjectAction.RUN_LINT,
    "RunTypecheck": ProjectAction.RUN_TYPECHECK,
    "InstallDependencies": ProjectAction.INSTALL_DEPENDENCIES,
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

    def __init__(
        self, workspace_root: Path | str, *, pre_authorized_operations: frozenset[str] = frozenset(),
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self._filesystem = FilesystemTool(workspace_root)
        self._git = GitTool(workspace_root)
        self._search = SearchTool(workspace_root)
        self._commands = CommandPlanner(workspace_root)
        self._permissions = PermissionEngine()
        self._pre_authorized = pre_authorized_operations

    async def execute(self, call: ToolCallRequest, *, agent: Agent) -> tuple[ToolCallResult, float]:
        """Returns (result, duration_seconds)."""
        start = time.monotonic()

        if call.name not in ALL_TOOL_SCHEMAS:
            return self._error_result(call, f"Unknown tool '{call.name}'."), 0.0

        decision = self._permissions.evaluate(
            PermissionRequest(
                agent=agent, operation=call.name, resource=str(call.arguments),
                pre_authorized=call.name in self._pre_authorized,
            )
        )
        if decision.action == PermissionAction.DENY:
            return self._error_result(call, f"Permission denied: {decision.reason}"), time.monotonic() - start
        if decision.action == PermissionAction.REQUIRE_CONFIRMATION:
            return (
                self._error_result(
                    call,
                    f"'{call.name}' requires explicit user confirmation ({decision.risk.value} risk) "
                    "and was not pre-authorized for this task.",
                ),
                time.monotonic() - start,
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
        name = call.name

        if name in _ACTION_BY_TOOL:
            result = await self._commands.run(_ACTION_BY_TOOL[name])
            return result.__dict__

        if name == "ReadFile":
            return self._filesystem.read_file(_require_str(args, "path"))

        if name == "ListFiles":
            entries = self._filesystem.list_dir(args.get("path", "."))
            return [entry.__dict__ for entry in entries]

        if name == "GetMetadata":
            return self._filesystem.metadata(_require_str(args, "path")).__dict__

        if name == "SearchFiles":
            matches = await self._search.search(_require_str(args, "query"))
            return [m.__dict__ for m in matches]

        if name == "WriteFile":
            path = _require_str(args, "path")
            content = _require_content(args)
            write_result = self._filesystem.write_file(path, content)
            return {
                "path": write_result.path, "backup_path": write_result.backup_path,
                "bytes_written": len(content.encode("utf-8")),
            }

        if name == "CreateFile":
            path = _require_str(args, "path")
            content = args.get("content", "")
            if not isinstance(content, str):
                raise ToolDeniedError("Tool argument 'content' must be a string.")
            create_result = self._filesystem.create_file(path, content)
            return {"path": create_result.path}

        if name == "DeleteFile":
            delete_result = self._filesystem.delete_file(_require_str(args, "path"))
            return {"path": delete_result.path, "backup_path": delete_result.backup_path}

        if name == "MoveFile":
            move_result = self._filesystem.move_file(_require_str(args, "source"), _require_str(args, "destination"))
            return {"path": move_result.path}

        if name == "CopyFile":
            copy_result = self._filesystem.copy_file(_require_str(args, "source"), _require_str(args, "destination"))
            return {"path": copy_result.path}

        if name == "GitStatus":
            return (await self._git.status()).__dict__

        if name == "GitDiff":
            return (await self._git.diff(staged=bool(args.get("staged", False)))).__dict__

        if name == "GitLog":
            return (await self._git.log(max_count=int(args.get("max_count", 20)))).__dict__

        if name == "GitShow":
            return (await self._git.show(_require_str(args, "revision"))).__dict__

        if name == "GitBranchList":
            return (await self._git.branch_list()).__dict__

        if name == "GitAdd":
            paths = args.get("paths")
            if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                raise ToolDeniedError("Tool argument 'paths' must be a list of strings.")
            return (await self._git.add(paths, authorized=True)).__dict__

        if name == "GitCommit":
            return (await self._git.commit(_require_str(args, "message"), authorized=True)).__dict__

        if name == "GitCheckout":
            return (await self._git.checkout(_require_str(args, "revision"), authorized=True)).__dict__

        if name == "GitCreateBranch":
            return (await self._git.create_branch(_require_str(args, "name"), authorized=True)).__dict__

        if name == "GitRevert":
            return (await self._git.revert(_require_str(args, "revision"), authorized=True)).__dict__

        if name == "GitMerge":
            return (await self._git.merge(_require_str(args, "revision"), authorized=True)).__dict__

        if name == "GitPush":
            return (await self._git.push(
                authorized=True, remote=args.get("remote", "origin"), branch=args.get("branch"),
            )).__dict__

        if name == "GitForcePush":
            return (await self._git.force_push(
                authorized=True, remote=args.get("remote", "origin"), branch=args.get("branch"),
            )).__dict__

        if name == "GitResetHard":
            return (await self._git.reset_hard(args.get("revision", "HEAD"), authorized=True)).__dict__

        if name == "GitCleanFd":
            return (await self._git.clean_fd(authorized=True)).__dict__

        if name == "GitBranchDelete":
            return (await self._git.branch_delete(_require_str(args, "name"), authorized=True)).__dict__

        raise NotFoundError(f"Unhandled tool '{name}'.")


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ToolDeniedError(f"Tool argument '{key}' is required and must be a non-empty string.")
    return value


def _require_content(args: dict[str, Any]) -> str:
    content = args.get("content")
    if not isinstance(content, str):
        raise ToolDeniedError("Tool argument 'content' is required and must be a string.")
    return content
