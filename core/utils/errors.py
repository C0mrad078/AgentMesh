"""Centralized error taxonomy for the Orquestrador core.

Every error that can cross the bridge into the frontend must be representable
as an `ErrorCode` + human-readable message + optional safe details. Raw
Python tracebacks or exception messages must never be forwarded verbatim to
the frontend, since they may leak file-system paths or internal state.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    UNKNOWN = "UNKNOWN"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNKNOWN_COMMAND = "UNKNOWN_COMMAND"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_INVALID_RESPONSE = "PROVIDER_INVALID_RESPONSE"
    PATH_TRAVERSAL_DENIED = "PATH_TRAVERSAL_DENIED"
    TOOL_DENIED = "TOOL_DENIED"
    DATABASE_ERROR = "DATABASE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class OrchestratorError(Exception):
    """Base class for all deliberate, well-typed errors in the core.

    Any exception subclassing this is safe to serialize and forward across
    the bridge: its `message` and `details` are considered non-sensitive by
    construction (callers are responsible for not putting secrets in them).
    """

    code: ErrorCode = ErrorCode.UNKNOWN

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "details": self.details}


class ValidationError(OrchestratorError):
    code = ErrorCode.VALIDATION_ERROR


class NotFoundError(OrchestratorError):
    code = ErrorCode.NOT_FOUND


class AlreadyExistsError(OrchestratorError):
    code = ErrorCode.ALREADY_EXISTS


class InvalidStateTransitionError(OrchestratorError):
    code = ErrorCode.INVALID_STATE_TRANSITION


class UnauthorizedError(OrchestratorError):
    code = ErrorCode.UNAUTHORIZED


class UnknownCommandError(OrchestratorError):
    code = ErrorCode.UNKNOWN_COMMAND


class TimeoutErrorX(OrchestratorError):
    """Named with an `X` suffix to avoid shadowing the builtin `TimeoutError`."""

    code = ErrorCode.TIMEOUT


class CancelledErrorX(OrchestratorError):
    code = ErrorCode.CANCELLED


class ProviderError(OrchestratorError):
    code = ErrorCode.PROVIDER_ERROR


class ProviderTimeoutError(ProviderError):
    code = ErrorCode.PROVIDER_TIMEOUT


class ProviderInvalidResponseError(ProviderError):
    code = ErrorCode.PROVIDER_INVALID_RESPONSE


class PathTraversalError(OrchestratorError):
    code = ErrorCode.PATH_TRAVERSAL_DENIED


class ToolDeniedError(OrchestratorError):
    code = ErrorCode.TOOL_DENIED


class DatabaseError(OrchestratorError):
    code = ErrorCode.DATABASE_ERROR


class InternalError(OrchestratorError):
    code = ErrorCode.INTERNAL_ERROR
