"""Normalized AI provider contract.

Every AI provider (mock, Anthropic/Claude, Google/Gemini, OpenAI/Codex, and
others later) implements `ProviderAdapter` and nothing else touches a
provider-specific SDK or wire format. The rest of the orchestrator only ever
sees the types defined here (`AIRequest`, `AIResponse`, `ToolCallRequest`,
`TokenUsage`, `ModelCapabilities`, ...) so adding a new provider is purely
additive: implement the adapter, register it in the model registry, done.

This module intentionally has zero knowledge of HTTP, SDKs, or any specific
provider's wire format -- that translation lives entirely inside each
`core/providers/<name>_provider.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ToolCallRequest:
    """A tool invocation an AI response asked for."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallResult:
    """The result of actually running a `ToolCallRequest`, fed back to the model."""

    id: str
    name: str
    output: Any
    error: str | None = None


@dataclass(frozen=True)
class ToolSchema:
    """A tool an agent is allowed to call, described as JSON schema."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Attachment:
    """A file/image made available to the model. Stage 2 only uses text
    attachments (file contents already read through `FilesystemTool`);
    binary/image attachments are represented the same way so a future
    multimodal provider path does not need a new type.
    """

    name: str
    mime_type: str
    content: str


@dataclass(frozen=True)
class AIMessage:
    role: MessageRole
    content: str
    tool_calls: tuple[ToolCallRequest, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None  # only set on role=TOOL messages


@dataclass(frozen=True)
class AIRequest:
    """The single, provider-agnostic shape every adapter's `execute`/`stream`
    receives. Nothing downstream of this needs to know which provider or
    model will actually serve it.
    """

    execution_id: str
    agent_id: str
    system_prompt: str
    messages: tuple[AIMessage, ...]
    tools: tuple[ToolSchema, ...] = ()
    structured_output_schema: dict[str, Any] | None = None
    attachments: tuple[Attachment, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    max_tokens: int | None = None
    temperature: float | None = None

    @classmethod
    def simple(
        cls,
        *,
        execution_id: str,
        agent_id: str,
        system_prompt: str,
        prompt: str,
        **kwargs: Any,
    ) -> AIRequest:
        """Convenience constructor for a single user-turn request."""
        return cls(
            execution_id=execution_id,
            agent_id=agent_id,
            system_prompt=system_prompt,
            messages=(AIMessage(role=MessageRole.USER, content=prompt),),
            **kwargs,
        )


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class AIResponse:
    """The single, provider-agnostic shape every adapter's `execute` returns.

    Deliberately excludes any private model "reasoning"/chain-of-thought
    field -- only the final content, tool calls, and objective metadata
    (usage, cost, duration, finish reason) are normalized and persisted.
    """

    content: str
    provider: str
    model: str
    finish_reason: str
    usage: TokenUsage
    duration_seconds: float
    tool_calls: tuple[ToolCallRequest, ...] = ()
    structured_output: dict[str, Any] | None = None
    estimated_cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCapabilities:
    supports_tools: bool = False
    supports_images: bool = False
    supports_files: bool = False
    supports_structured_output: bool = False
    context_window: int = 8192


class ProviderHealthStatus(str, Enum):
    """Ongoing health of a provider, as tracked by `core.providers.health` and
    consulted by the Router. Distinct from `ConnectionTestResult`, which is
    the one-shot outcome of a user-triggered "Test Connection" action.
    """

    ONLINE = "online"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ConnectionTestResult(str, Enum):
    CONNECTED = "connected"
    INVALID_KEY = "invalid_key"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNKNOWN_ERROR = "unknown_error"


class ProviderAdapter(ABC):
    """Common interface every AI provider adapter must implement."""

    name: str

    @abstractmethod
    async def execute(self, request: AIRequest) -> AIResponse:
        """Run one unit of work and return its result.

        Implementations must raise `core.utils.errors.ProviderError` (or a
        subclass) on failure -- never a bare/unknown exception -- so the
        executor can apply a uniform retry/backoff policy and the circuit
        breaker can classify failures correctly.
        """
        ...

    @abstractmethod
    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        """Yield content deltas as they arrive.

        Not currently consumed by the Stage 2 executor (which needs one
        complete `AIResponse` per step to persist and verify), but part of
        the contract so a live-token UI can be added later without changing
        the adapter interface.
        """
        ...
        yield ""  # pragma: no cover - abstract generator marker

    @abstractmethod
    async def health_check(self) -> ProviderHealthStatus:
        """Report whether the provider is currently reachable/usable."""
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return model ids this provider currently exposes, if discoverable.

        Providers that cannot enumerate models dynamically (or whose API key
        is not configured) should return an empty list rather than raising --
        the model registry's static configuration is the source of truth
        either way (see `core/providers/registry.py`).
        """
        ...

    @abstractmethod
    async def cancel(self, execution_id: str) -> None:
        """Best-effort cancellation of an in-flight request by id."""
        ...
