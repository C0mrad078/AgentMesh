"""Provider adapter contract.

Every AI provider (mock today; Claude, Gemini, OpenAI/Codex, and others
later) implements this interface and nothing else touches the orchestrator.
No module outside `core/providers/` is allowed to import a provider-specific
SDK, so adding a new provider is purely additive: implement
`ProviderAdapter`, register it, done.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderRequestKind(str, Enum):
    GENERATE = "generate"
    REVIEW = "review"
    VERIFY = "verify"


@dataclass(frozen=True)
class ProviderRequest:
    kind: ProviderRequestKind
    prompt: str
    agent_id: str
    context: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ProviderResult:
    output: str
    raw: dict[str, Any] = field(default_factory=dict)
    tokens_used: int | None = None


class ProviderHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderAdapter(ABC):
    """Common interface every AI provider adapter must implement."""

    name: str

    @abstractmethod
    async def execute(self, request: ProviderRequest) -> ProviderResult:
        """Run one unit of work and return its result.

        Implementations must raise `core.providers.exceptions.ProviderError`
        (or a subclass) on failure -- never a bare/unknown exception -- so
        the executor can apply a uniform retry/backoff policy.
        """
        ...

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Report whether the provider is currently reachable/usable."""
        ...

    @abstractmethod
    async def cancel(self, request_id: str) -> None:
        """Best-effort cancellation of an in-flight request by id."""
        ...
