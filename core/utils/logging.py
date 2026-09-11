"""Structured logging for the core.

Critical invariant: the bridge protocol uses stdout as its transport
(newline-delimited JSON messages exchanged with the Tauri parent process).
Therefore **no log line may ever be written to stdout** — every handler
here targets stderr or a rotating log file under the platform log
directory. Writing a stray `print()` anywhere in the core would corrupt the
bridge stream, so this module also patches `sys.stdout` during sidecar
startup to catch accidental writes early (see `guard_stdout`).

Secrets (API keys, tokens, passwords, full credential blobs) must never be
logged. `redact()` provides a conservative helper for call sites that build
log context dictionaries from user- or provider-supplied data.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "credential",
    "credentials",
    "authorization",
    "session_token",
}


def redact(context: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of `context` with sensitive-looking keys masked."""
    safe: dict[str, Any] = {}
    for key, value in context.items():
        if key.lower() in _SENSITIVE_KEYS:
            safe[key] = "***REDACTED***"
        elif isinstance(value, dict):
            safe[key] = redact(value)
        else:
            safe[key] = value
    return safe


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "module": record.name,
            "event": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if context:
            payload["context"] = redact(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(*, log_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure the root `orchestrator` logger.

    All handlers write to stderr and/or a file — never stdout.
    """
    logger = logging.getLogger("orchestrator")
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(_JsonFormatter())
    logger.addHandler(stderr_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "orchestrator-core.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(_JsonFormatter())
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"orchestrator.{name}")


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    execution_id: str | None = None,
    task_id: str | None = None,
    **context: Any,
) -> None:
    """Emit a structured log event with the standard context fields."""
    ctx = dict(context)
    if execution_id is not None:
        ctx["execution_id"] = execution_id
    if task_id is not None:
        ctx["task_id"] = task_id
    logger.log(level, event, extra={"context": ctx})


class _StdoutGuard:
    """A stdout stand-in that raises instead of silently corrupting the bridge."""

    def write(self, data: str) -> int:
        if data.strip():
            raise RuntimeError(
                "Attempted to write to stdout while the bridge protocol owns it. "
                "Use core.utils.logging.get_logger(...) instead of print()."
            )
        return len(data)

    def flush(self) -> None:
        return None


@contextmanager
def guard_stdout() -> Iterator[None]:
    """Temporarily replace `sys.stdout` to catch accidental prints.

    The bridge server itself writes protocol frames through a captured
    reference to the *real* stdout obtained before this guard is installed.
    """
    original = sys.stdout
    sys.stdout = _StdoutGuard()
    try:
        yield
    finally:
        sys.stdout = original
