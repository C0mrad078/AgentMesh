"""Translate any exception raised while handling a bridge request into a
safe, structured `ErrorPayload` -- never a raw traceback or exception
string that might leak internal paths or details to the frontend.
"""

from __future__ import annotations

from core.bridge.protocol import ErrorPayload
from core.utils.errors import ErrorCode, OrchestratorError
from core.utils.logging import get_logger

logger = get_logger("bridge.errors")


def to_error_payload(exc: Exception) -> ErrorPayload:
    if isinstance(exc, OrchestratorError):
        return ErrorPayload(code=exc.code.value, message=exc.message, details=exc.details)

    logger.error("unhandled_exception", extra={"context": {"type": type(exc).__name__}})
    return ErrorPayload(
        code=ErrorCode.INTERNAL_ERROR.value,
        message="An internal error occurred while processing the request.",
        details={},
    )
