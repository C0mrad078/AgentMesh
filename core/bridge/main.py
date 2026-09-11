"""Sidecar entrypoint: `python -m core.bridge.main`.

Launched by Tauri as a child process with stdio piped. Required environment
variables (set by the Tauri Rust side when spawning the sidecar):

  * `ORCH_SESSION_TOKEN` -- shared secret proving requests come from the
    process that spawned this one. Required.
  * `ORCH_DATA_DIR`      -- optional override for the application data
    directory (used by dev/test to avoid touching the real user profile).

Every log line goes to stderr and/or the rotating log file under the
platform log directory -- never stdout, which is reserved entirely for the
bridge protocol. `guard_stdout()` wraps the whole run so an accidental
`print()` anywhere in the dependency tree fails loudly instead of silently
corrupting a response line.
"""

from __future__ import annotations

import asyncio
import os
import sys

from core.bridge.context import build_context
from core.bridge.server import BridgeServer, make_event_sink
from core.bridge.transport import StdioTransport
from core.orchestrator.recovery import recover_interrupted_work
from core.utils.logging import configure_logging, get_logger, guard_stdout
from core.utils.platform import get_app_paths

logger = get_logger("bridge.main")


async def _async_main() -> int:
    session_token = os.environ.get("ORCH_SESSION_TOKEN")
    if not session_token:
        logger.error("missing_session_token")
        return 1

    override_root = os.environ.get("ORCH_DATA_DIR")
    paths = get_app_paths(override_root=override_root)
    configure_logging(log_dir=paths.log_dir)

    transport = StdioTransport()
    sink = make_event_sink(transport)
    context = await build_context(paths.db_path, event_sink=sink)

    report = await recover_interrupted_work(context.task_service, context.executions_repo)
    if report.recovered_task_ids or report.recovered_execution_ids:
        logger.warning(
            "startup_recovery_completed",
            extra={
                "context": {
                    "tasks": len(report.recovered_task_ids),
                    "executions": len(report.recovered_execution_ids),
                }
            },
        )

    server = BridgeServer(transport, session_token, context)
    try:
        with guard_stdout():
            await server.serve_forever()
    finally:
        await context.db.close()
    return 0


def main() -> None:
    try:
        exit_code = asyncio.run(_async_main())
    except KeyboardInterrupt:
        exit_code = 0
    except Exception:
        logger.exception("fatal_error")
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
