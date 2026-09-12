"""Sidecar entrypoint: `python -m core.bridge.main`.

Launched by Tauri as a child process with stdio piped. Required environment
variables (set by the Tauri Rust side when spawning the sidecar):

  * `ORCH_SESSION_TOKEN` -- shared secret proving requests come from the
    process that spawned this one. Required.
  * `ORCH_DATA_DIR`      -- optional override for the application data
    directory (used by dev/test to avoid touching the real user profile).
  * `ORCH_ENABLE_MOCK_PROVIDER` -- test-only opt-in ("1"/"true"). Registers
    `MockProvider` in the provider pool alongside whatever real providers
    are configured, so the end-to-end smoke test can exercise the full
    autonomous pipeline deterministically without real API keys. Never set
    by the desktop app itself.

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
from core.bridge.server import BridgeServer, make_event_sink, make_orchestration_event_sink
from core.bridge.transport import StdioTransport
from core.orchestrator.recovery import recover_interrupted_work
from core.providers.base import ProviderAdapter
from core.providers.mock_provider import MockProvider
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
    orchestration_sink = make_orchestration_event_sink(transport)

    provider_overrides: dict[str, ProviderAdapter] | None = None
    if os.environ.get("ORCH_ENABLE_MOCK_PROVIDER", "").lower() in ("1", "true"):
        provider_overrides = {"mock": MockProvider()}

    context = await build_context(
        paths.db_path, event_sink=sink, orchestration_event_sink=orchestration_sink,
        provider_overrides=provider_overrides,
    )

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
        await context.close()
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
