"""Minimal, safe git operations.

Only a fixed set of read-only git subcommands are exposed, each invoked as
an explicit argument vector through `core.utils.shell_runner`, always with
`cwd` pinned to the tool's workspace root. There is no method that accepts
caller-supplied git arguments.
"""

from __future__ import annotations

from pathlib import Path

from core.tools.base import Tool
from core.utils.errors import ToolDeniedError
from core.utils.shell_runner import RunResult, get_runner

_GIT_TIMEOUT_SECONDS = 15.0


class GitTool(Tool):
    name = "git"

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        self._runner = get_runner()

    async def _run(self, args: list[str]) -> RunResult:
        if not self.workspace_root.exists():
            raise ToolDeniedError(f"Workspace root '{self.workspace_root}' does not exist.")
        return await self._runner.run(
            ["git", *args], cwd=self.workspace_root, timeout=_GIT_TIMEOUT_SECONDS
        )

    async def status(self) -> RunResult:
        return await self._run(["status", "--porcelain=v1", "--branch"])

    async def diff(self, *, staged: bool = False) -> RunResult:
        args = ["diff", "--no-color"]
        if staged:
            args.append("--staged")
        return await self._run(args)

    async def is_repository(self) -> bool:
        result = await self._run(["rev-parse", "--is-inside-work-tree"])
        return result.success and result.stdout.strip() == "true"
