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

Stage 4 hardening on top of the Stage 1 baseline:

  * **Minimal environment** -- child processes get a small, explicit
    allowlist of variables (`PATH`, home dir, temp dir, locale, and the
    Windows variables subprocess resolution itself needs), never the
    full parent environment (which may carry secrets in some deployment
    environments even though this app's own credentials never live in
    env vars). Callers can layer extra variables on top via `env=`.
  * **Output caps** -- `max_stdout_bytes`/`max_stderr_bytes` bound how
    much of a runaway process's output is ever held in memory; the
    stream is still drained past the cap (discarding the excess) so a
    chatty child can't deadlock on a full pipe buffer while the cap is
    enforced.
  * **Process-tree termination** -- both the timeout path and explicit
    cancellation kill the whole process group, not just the immediate
    child, so `npm`/`pytest`/build-tool subprocesses that fork further
    children don't survive a cancelled command.
  * **Cooperative cancellation** -- an optional `cancel_event` is raced
    against the running process, mirroring `StepExecutor`'s provider
    cancellation.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from core.utils.errors import CancelledErrorX, ToolDeniedError
from core.utils.platform import is_windows

_DEFAULT_MAX_OUTPUT_BYTES = 1 * 1024 * 1024  # 1 MiB per stream
_GRACE_PERIOD_SECONDS = 3.0
_TRUNCATION_MARKER = "\n...[output truncated by the Orquestrador's output size limit]"

#: Variables a child process needs to resolve executables and behave
#: predictably, and nothing else. Secrets (API keys, tokens) are never in
#: this list -- they live exclusively in the OS keychain/credential
#: manager (see `core.security.secret_store`), never in process env vars,
#: so there is nothing sensitive to accidentally forward here; the
#: allowlist exists anyway as defense in depth against a future variable
#: being added carelessly to the *parent* process's own environment.
_INHERITED_ENV_VARS = (
    "PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
    "SYSTEMROOT", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA",
)


def _minimal_env(extra: dict[str, str] | None) -> dict[str, str]:
    base = {key: os.environ[key] for key in _INHERITED_ENV_VARS if key in os.environ}
    if extra:
        base.update(extra)
    return base


@dataclass(frozen=True)
class RunResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int


async def _read_capped(stream: asyncio.StreamReader, max_bytes: int) -> bytes:
    """Drain `stream` to EOF, keeping only the first `max_bytes`. Draining
    past the cap (rather than stopping) prevents a chatty child from
    blocking forever on a full pipe buffer once we stop reading."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        if total < max_bytes:
            room = max_bytes - total
            chunks.append(chunk[:room])
        total += len(chunk)
    data = b"".join(chunks)
    if total > max_bytes:
        data += _TRUNCATION_MARKER.encode()
    return data


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """Kill the process and every descendant it spawned, not just the
    immediate child -- required for build tools/test runners that fork
    further subprocesses (npm, pytest, etc.)."""
    if process.returncode is not None:
        return
    try:
        if is_windows():
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/T", "/F", "/PID", str(process.pid),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=_GRACE_PERIOD_SECONDS)
            except TimeoutError:
                os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # already gone
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()


async def _exec(
    argv: list[str],
    *,
    cwd: Path | None,
    timeout: float,
    env: dict[str, str] | None,
    cancel_event: asyncio.Event | None,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> RunResult:
    resolved_cwd = str(cwd) if cwd is not None else None
    resolved_env = _minimal_env(env)
    try:
        if is_windows():
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=resolved_cwd, env=resolved_env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined]
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=resolved_cwd, env=resolved_env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # own process group, for tree-kill
            )
    except FileNotFoundError as exc:
        raise ToolDeniedError(f"Executable not found: {argv[0]!r}") from exc

    async def _collect() -> tuple[bytes, bytes]:
        assert process.stdout is not None
        assert process.stderr is not None
        return await asyncio.gather(
            _read_capped(process.stdout, max_stdout_bytes),
            _read_capped(process.stderr, max_stderr_bytes),
        )

    collect_task = asyncio.ensure_future(_collect())
    wait_tasks: list[asyncio.Future] = [collect_task]
    cancel_wait_task = None
    if cancel_event is not None:
        cancel_wait_task = asyncio.ensure_future(cancel_event.wait())
        wait_tasks.append(cancel_wait_task)

    done, _ = await asyncio.wait(wait_tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)

    if cancel_wait_task is not None and cancel_wait_task in done:
        collect_task.cancel()
        await _terminate_process_tree(process)
        raise CancelledErrorX(f"Command '{argv[0]}' was cancelled.")

    if collect_task not in done:
        if cancel_wait_task is not None:
            cancel_wait_task.cancel()
        collect_task.cancel()
        await _terminate_process_tree(process)
        raise ToolDeniedError(f"Command '{argv[0]}' timed out after {timeout}s.")

    if cancel_wait_task is not None:
        cancel_wait_task.cancel()
    stdout_bytes, stderr_bytes = collect_task.result()
    await process.wait()

    return RunResult(
        success=process.returncode == 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        returncode=process.returncode or 0,
    )


class ShellRunner(ABC):
    @abstractmethod
    async def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 10.0,
        env: dict[str, str] | None = None,
        cancel_event: asyncio.Event | None = None,
        max_stdout_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
        max_stderr_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
    ) -> RunResult: ...


class PosixRunner(ShellRunner):
    async def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 10.0,
        env: dict[str, str] | None = None,
        cancel_event: asyncio.Event | None = None,
        max_stdout_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
        max_stderr_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
    ) -> RunResult:
        return await _exec(
            argv, cwd=cwd, timeout=timeout, env=env, cancel_event=cancel_event,
            max_stdout_bytes=max_stdout_bytes, max_stderr_bytes=max_stderr_bytes,
        )


class PowerShellRunner(ShellRunner):
    async def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 10.0,
        env: dict[str, str] | None = None,
        cancel_event: asyncio.Event | None = None,
        max_stdout_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
        max_stderr_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
    ) -> RunResult:
        return await _exec(
            argv, cwd=cwd, timeout=timeout, env=env, cancel_event=cancel_event,
            max_stdout_bytes=max_stdout_bytes, max_stderr_bytes=max_stderr_bytes,
        )


def get_runner() -> ShellRunner:
    """Return the appropriate runner for the current OS.

    This is the only call site in the codebase that should ever ask
    "is this Windows?" purely to decide how to run a subprocess.
    """
    return PowerShellRunner() if is_windows() else PosixRunner()
