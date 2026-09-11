"""Agent domain model.

An `Agent` is a configured persona bound to a provider/model pair, with an
explicit capability and permission surface. In this stage every agent is
backed by `MockProvider`, but the shape already carries everything a real
Claude/Gemini/Codex-backed agent will need so wiring in real providers later
is additive rather than a redesign.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentCapability(BaseModel):
    """A named capability an agent claims to support (e.g. 'code_review')."""

    name: str
    description: str = ""


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
