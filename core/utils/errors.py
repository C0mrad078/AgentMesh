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
    PROVIDER_AUTHENTICATION_ERROR = "PROVIDER_AUTHENTICATION_ERROR"
    PROVIDER_RATE_LIMIT_ERROR = "PROVIDER_RATE_LIMIT_ERROR"
    PROVIDER_UNAVAILABLE_ERROR = "PROVIDER_UNAVAILABLE_ERROR"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"
    BUDGET_EXCEEDED_ERROR = "BUDGET_EXCEEDED_ERROR"
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
    """Base for every error a `ProviderAdapter` can raise.

    `retryable` drives the Executor's retry policy: only errors that are
    plausibly transient (timeouts, rate limits, 5xx/unavailable) should ever
    be retried automatically. Authentication errors, invalid responses, and
    anything else that will deterministically fail again are not retryable
    -- retrying them would just waste time/tokens and mask the real problem.
    """

    code = ErrorCode.PROVIDER_ERROR
    retryable: bool = False


class ProviderTimeoutError(ProviderError):
    code = ErrorCode.PROVIDER_TIMEOUT
    retryable = True


class ProviderInvalidResponseError(ProviderError):
    code = ErrorCode.PROVIDER_INVALID_RESPONSE
    retryable = False


class ProviderAuthenticationError(ProviderError):
    """Invalid/missing API key. Never retryable -- the same key will fail
    again immediately; the user needs to fix the credential instead.
    """

    code = ErrorCode.PROVIDER_AUTHENTICATION_ERROR
    retryable = False


class ProviderRateLimitError(ProviderError):
    code = ErrorCode.PROVIDER_RATE_LIMIT_ERROR
    retryable = True

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailableError(ProviderError):
    """5xx / connection failure / provider-reported outage."""

    code = ErrorCode.PROVIDER_UNAVAILABLE_ERROR
    retryable = True


class ToolExecutionError(OrchestratorError):
    code = ErrorCode.TOOL_EXECUTION_ERROR


class VerificationError(OrchestratorError):
    """Raised when a verification step cannot even be attempted (e.g. a
    malformed verification request) -- a normal verification *failure* is
    represented by `VerificationResult(passed=False, ...)`, not an
    exception; this is for the verifier itself being unable to run.
    """

    code = ErrorCode.VERIFICATION_ERROR


class BudgetExceededError(OrchestratorError):
    code = ErrorCode.BUDGET_EXCEEDED_ERROR


class PathTraversalError(OrchestratorError):
    code = ErrorCode.PATH_TRAVERSAL_DENIED


class ToolDeniedError(OrchestratorError):
    code = ErrorCode.TOOL_DENIED


class DatabaseError(OrchestratorError):
    code = ErrorCode.DATABASE_ERROR


class InternalError(OrchestratorError):
    code = ErrorCode.INTERNAL_ERROR
