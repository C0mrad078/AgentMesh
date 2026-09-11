"""Line-based stdio transport for the bridge.

Deliberately implemented with plain blocking file objects dispatched
through the default executor (`loop.run_in_executor`) rather than
`loop.connect_read_pipe` / `connect_write_pipe`. The latter rely on pipe
transports whose behavior around real console handles differs between
POSIX and Windows (ProactorEventLoop); wrapping the ordinary, well-defined
blocking `readline`/`write` calls sidesteps that entirely and behaves
identically on macOS, Windows, and Linux, since a subprocess's redirected
stdio is a plain readable/writable stream on every platform.

`stdout` here always refers to the *real* stdout captured at process
startup, before `core.utils.logging.guard_stdout` replaces `sys.stdout` to
catch accidental `print()` calls elsewhere in the process.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import IO


class StdioTransport:
    def __init__(
        self,
        *,
        stdin: IO[str] | None = None,
        write_line_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._stdin = stdin or sys.stdin
        self._real_stdout = sys.stdout
        self._write_line_fn = write_line_fn or self._default_write
        self._write_lock = asyncio.Lock()

    def _default_write(self, line: str) -> None:
        self._real_stdout.write(line + "\n")
        self._real_stdout.flush()

    async def read_line(self) -> str | None:
        """Read one line, or return None at EOF (parent closed the pipe)."""
        loop = asyncio.get_event_loop()
        line = await loop.run_in_executor(None, self._stdin.readline)
        if line == "":
            return None
        return line.rstrip("\n")

    async def write_line(self, data: str) -> None:
        loop = asyncio.get_event_loop()
        async with self._write_lock:
            await loop.run_in_executor(None, self._write_line_fn, data)
