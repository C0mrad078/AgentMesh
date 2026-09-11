"""Controlled terminal access.

This is deliberately not a general-purpose shell tool. Agents (and the
orchestrator) can only request one of a fixed set of pre-approved,
zero-argument diagnostic commands via `TerminalCommand`. There is no code
path anywhere that accepts a free-form string and hands it to a shell --
adding a new capability means adding a new enum member and its fixed
argument vector, reviewed like any other code change. Execution itself goes
through `core.utils.shell_runner`, the same choke point `GitTool` uses.
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

from core.tools.base import Tool
from core.utils.errors import ToolDeniedError
from core.utils.shell_runner import RunResult, get_runner

_TIMEOUT_SECONDS = 10.0


class TerminalCommand(str, Enum):
    PYTHON_VERSION = "python_version"
    WORKING_DIRECTORY = "working_directory"


_COMMANDS: dict[TerminalCommand, list[str]] = {
    TerminalCommand.PYTHON_VERSION: [sys.executable, "--version"],
    TerminalCommand.WORKING_DIRECTORY: (
        ["cmd", "/c", "cd"] if sys.platform == "win32" else ["pwd"]
    ),
}


class TerminalTool(Tool):
    name = "terminal"

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        self._runner = get_runner()

    async def run(self, command: TerminalCommand) -> RunResult:
        argv = _COMMANDS.get(command)
        if argv is None:
            raise ToolDeniedError(f"Terminal command '{command}' is not in the allowlist.")

        cwd = self.workspace_root if self.workspace_root.exists() else None
        return await self._runner.run(argv, cwd=cwd, timeout=_TIMEOUT_SECONDS)
