"""Shell execution abstraction.

Every subprocess launched anywhere in the core goes through a `ShellRunner`
obtained from `get_runner()`, never through an ad hoc
`asyncio.create_subprocess_exec` call scattered in tool code. This is the
single choke point requested by the project's portability rules: platform
detection stays in `core.utils.platform`, and *this* module is the only
place that turns "which OS am I on" into "how do I run a process."

Both concrete runners execute the given argument vector directly (no shell
string interpolation) -- this is deliberate, not a shortcut: every
argument vector reaching this layer is already a fixed, hardcoded list (see
`core.tools.terminal_tool` and `core.tools.git_tool`), never
attacker/agent-controlled text, so routing it through `sh -c` or
`powershell -Command` would only add a shell-injection surface for zero
benefit. `PosixRunner` and `PowerShellRunner` exist as distinct classes
anyway so:

  1. call sites never branch on OS themselves (`get_runner()` does that
     once, centrally), and
  2. if a future capability genuinely needs POSIX shell builtins vs. a
     PowerShell cmdlet, there is already exactly one reviewed place per
     platform to add that -- not a new conditional at every call site.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from core.utils.errors import ToolDeniedError
from core.utils.platform import is_windows


@dataclass(frozen=True)
class RunResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int


async def _exec(argv: list[str], *, cwd: Path | None, timeout: float) -> RunResult:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ToolDeniedError(f"Executable not found: {argv[0]!r}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ToolDeniedError(f"Command '{argv[0]}' timed out after {timeout}s.") from exc

    return RunResult(
        success=process.returncode == 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        returncode=process.returncode or 0,
    )


class ShellRunner(ABC):
    @abstractmethod
    async def run(
        self, argv: list[str], *, cwd: Path | None = None, timeout: float = 10.0
    ) -> RunResult: ...


class PosixRunner(ShellRunner):
    async def run(
        self, argv: list[str], *, cwd: Path | None = None, timeout: float = 10.0
    ) -> RunResult:
        return await _exec(argv, cwd=cwd, timeout=timeout)


class PowerShellRunner(ShellRunner):
    async def run(
        self, argv: list[str], *, cwd: Path | None = None, timeout: float = 10.0
    ) -> RunResult:
        return await _exec(argv, cwd=cwd, timeout=timeout)


def get_runner() -> ShellRunner:
    """Return the appropriate runner for the current OS.

    This is the only call site in the codebase that should ever ask
    "is this Windows?" purely to decide how to run a subprocess.
    """
    return PowerShellRunner() if is_windows() else PosixRunner()
