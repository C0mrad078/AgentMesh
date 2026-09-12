"""Stage 4 shell runner hardening: output caps, minimal environment,
process-tree termination, and cooperative cancellation.

POSIX-only (the sandbox this runs in is macOS/Linux); Windows-specific
paths (`taskkill`, `CREATE_NEW_PROCESS_GROUP`) are exercised by code
review and by `core.tools.git_tool`/`core.tools.terminal_tool` continuing
to pass their existing cross-platform-agnostic tests, not by a live
Windows process tree here -- see the Stage 4 report's "UNVERIFIED
EXTERNAL DEPENDENCY" section.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from core.utils.errors import CancelledErrorX, ToolDeniedError
from core.utils.shell_runner import PosixRunner

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process-tree test")


async def test_output_beyond_the_cap_is_truncated_not_dropped_entirely() -> None:
    runner = PosixRunner()
    result = await runner.run(
        ["python3", "-c", "print('x' * 200)"], timeout=5.0, max_stdout_bytes=50,
    )
    assert result.success
    assert len(result.stdout.encode()) < 250  # capped, plus a short marker
    assert "truncated" in result.stdout


async def test_a_chatty_process_past_the_cap_does_not_hang() -> None:
    # Writes far more than the cap and would block on a full pipe if the
    # runner stopped draining instead of discarding past the limit.
    runner = PosixRunner()
    result = await runner.run(
        ["python3", "-c", "import sys\nfor _ in range(20000): sys.stdout.write('y' * 100)"],
        timeout=5.0, max_stdout_bytes=100,
    )
    assert result.success


async def test_minimal_environment_does_not_leak_arbitrary_parent_vars() -> None:
    os.environ["ORCH_TEST_SECRET_LOOKING_VAR"] = "should-not-be-inherited"
    try:
        runner = PosixRunner()
        result = await runner.run(
            ["python3", "-c", "import os; print(os.environ.get('ORCH_TEST_SECRET_LOOKING_VAR', 'ABSENT'))"],
            timeout=5.0,
        )
        assert result.stdout.strip() == "ABSENT"
    finally:
        del os.environ["ORCH_TEST_SECRET_LOOKING_VAR"]


async def test_explicit_env_override_is_still_passed_through() -> None:
    runner = PosixRunner()
    result = await runner.run(
        ["python3", "-c", "import os; print(os.environ.get('ORCH_EXPLICIT'))"],
        timeout=5.0, env={"ORCH_EXPLICIT": "yes"},
    )
    assert result.stdout.strip() == "yes"


async def test_timeout_kills_the_whole_process_tree(tmp_path) -> None:
    marker = tmp_path / "child_alive"
    # Parent spawns a child that keeps touching `marker`'s mtime; if only
    # the parent were killed (not the tree), the child would keep running
    # after the timeout fires.
    child_script = tmp_path / "child.py"
    child_script.write_text(
        "import time\n"
        f"marker = {str(marker)!r}\n"
        "while True:\n"
        "    open(marker, 'w').write(str(time.time()))\n"
        "    time.sleep(0.2)\n"
    )
    parent_script = tmp_path / "parent.py"
    parent_script.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(child_script)!r}])\n"
        "time.sleep(30)\n"
    )
    runner = PosixRunner()
    with pytest.raises(ToolDeniedError):
        await runner.run(["python3", str(parent_script)], timeout=1.0)

    await asyncio.sleep(0.5)
    assert marker.exists()
    mtime_after_kill = marker.stat().st_mtime
    await asyncio.sleep(1.0)
    # The child should not have touched the marker again after the tree was killed.
    assert marker.stat().st_mtime == mtime_after_kill


async def test_cancel_event_terminates_the_process_before_timeout() -> None:
    runner = PosixRunner()
    cancel_event = asyncio.Event()

    async def _cancel_soon() -> None:
        await asyncio.sleep(0.2)
        cancel_event.set()

    asyncio.ensure_future(_cancel_soon())
    with pytest.raises(CancelledErrorX):
        await runner.run(["python3", "-c", "import time; time.sleep(10)"], timeout=30.0, cancel_event=cancel_event)


async def test_missing_executable_raises_tool_denied() -> None:
    runner = PosixRunner()
    with pytest.raises(ToolDeniedError):
        await runner.run(["this-binary-does-not-exist-anywhere"], timeout=2.0)


async def test_child_stdin_is_devnull_not_inherited_from_the_parent() -> None:
    # `asyncio.create_subprocess_exec` inherits the parent's stdin unless
    # told otherwise -- in production, the orchestrator's own stdin is the
    # Rust<->Python JSON-lines bridge pipe. A spawned child (a CLI provider,
    # git, a project command) reading from an inherited stdin could steal
    # bytes meant for that protocol, or hang forever waiting for input that
    # will never arrive. `sys.stdin.read()` must see immediate EOF (`''`),
    # not block.
    runner = PosixRunner()
    result = await runner.run(
        ["python3", "-c", "import sys; data = sys.stdin.read(); print(repr(data))"],
        timeout=3.0,
    )
    assert result.success
    assert "''" in result.stdout


async def test_stdin_data_is_piped_without_deadlocking_on_large_output() -> None:
    # A naive write-then-read implementation deadlocks here: a large stdin
    # payload and a child that echoes a lot back on stdout can each fill
    # their pipe's OS buffer while waiting on the other side.
    runner = PosixRunner()
    payload = b"x" * (256 * 1024)
    result = await runner.run(
        ["python3", "-c", "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"],
        timeout=10.0,
        stdin_data=payload,
    )
    assert result.success
    assert len(result.stdout.encode()) == len(payload)


async def test_no_stdin_data_still_closes_stdin_as_devnull() -> None:
    runner = PosixRunner()
    result = await runner.run(
        ["python3", "-c", "import sys; print(repr(sys.stdin.read()))"],
        timeout=3.0,
    )
    assert result.success
    assert "''" in result.stdout


async def test_user_env_var_is_inherited_for_keychain_based_cli_tools() -> None:
    # Real, live-verified finding: `claude auth status` reports
    # `loggedIn: false` for an already-authenticated account when `USER`
    # is missing from the child's environment (its Keychain lookup depends
    # on it). `USER` is exactly as benign as `HOME`, already inherited.
    os.environ.setdefault("USER", "someone")
    runner = PosixRunner()
    result = await runner.run(
        ["python3", "-c", "import os; print(os.environ.get('USER', 'ABSENT'))"],
        timeout=5.0,
    )
    assert result.stdout.strip() == os.environ["USER"]
