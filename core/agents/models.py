"""Agent domain model.

An `Agent` is a configured persona bound to a provider/model pair, with an
explicit capability and permission surface. In this stage every agent is
backed by `MockProvider`, but the shape already carries everything a real
Claude/Gemini/Codex-backed agent will need so wiring in real providers later
is additive rather than a redesign.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from core.runtime.execution_backend import ExecutionBackendType


class AgentCapability(BaseModel):
    """A named capability an agent claims to support (e.g. 'code_review')."""

    name: str
    description: str = ""


class AgentStatus(str, Enum):
    """Refactor V2, Phase 1: a place for Phase 8's Presence Engine to write
    real, event-derived state later. Nothing in Phase 1 computes or
    displays this -- it is inert schema, not a claimed live signal (see
    docs/refactor-v2-plan.md §4). `IDLE` is the default precisely because
    "no session has ever driven this agent" and "genuinely idle" look the
    same from the persistence layer's point of view."""

    IDLE = "idle"
    WORKING = "working"
    OFFLINE = "offline"


class AgentPermissions(BaseModel):
    can_read_files: bool = True
    can_write_files: bool = False
    can_run_git: bool = False
    can_run_terminal: bool = False
    max_tokens_per_call: int | None = None


class Agent(BaseModel):
    id: str
    name: str
    description: str = ""
    provider: str
    model: str = ""
    system_prompt: str = ""
    capabilities: list[AgentCapability] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    permissions: AgentPermissions = Field(default_factory=AgentPermissions)
    config: dict[str, str] = Field(default_factory=dict)
    active: bool = True
    # Stage 3, spec section 9/44/45: the agent (a logical role -- "Frontend
    # Developer") is not the provider that happens to execute it right now.
    # `provider` above stays the *effective* provider `Router` uses by
    # default; `fallback_providers` is the ordered, explicit declaration of
    # what this agent may fall back to if its own provider is unavailable
    # -- read by the UI (tooltip: "Provider: Claude Code / Fallback from:
    # Codex") and satisfied in practice by `Router`'s capability-pool +
    # `exclude_agent_ids` mechanism (any other agent sharing this one's
    # capability is already a real candidate once this one is excluded --
    # see `core.orchestrator.engine._run_correction_round`), plus a real
    # weighted scoring preference inside `Router._score`
    # (`preferred_fallback_providers`, see
    # `tests/integration/test_provider_fallback.py` and
    # `tests/python/test_router.py::test_fallback_preference_bonus_*`) so a
    # reroute favors a *declared* fallback over an arbitrary other
    # candidate that merely shares the capability.
    preferred_provider: str | None = None
    fallback_providers: list[str] = Field(default_factory=list)
    # Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): the office/runtime
    # fields the new architecture needs. `role`/`avatar` are display
    # concerns (e.g. "Software Architect", an avatar preset id) distinct
    # from `capabilities` (routing-relevant). `preferred_backend`/
    # `fallback_backend` are the Subscription/Session/API axis -- distinct
    # from and orthogonal to `preferred_provider`/`fallback_providers`
    # above, which is the *which provider* axis.
    role: str = ""
    avatar: str | None = None
    status: AgentStatus = AgentStatus.IDLE
    preferred_backend: ExecutionBackendType | None = None
    fallback_backend: ExecutionBackendType | None = None
    memory_profile: dict[str, str] = Field(default_factory=dict)

    @property
    def effective_preferred_provider(self) -> str:
        return self.preferred_provider or self.provider
