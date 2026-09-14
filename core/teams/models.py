"""Team domain models (Refactor V2, Phase 1).

A `Team` is a persistent grouping of agents, optionally scoped to one
project (`project_id`; nullable -- a team can exist before being assigned
to a project). Membership is many-to-many via the `team_agents` join table
(`TeamsRepository.add_agent`/`remove_agent`/`list_agent_ids`) -- no
Team<->Project join table exists, since the brief's own `Team` shape is a
single `project_id` field, not a many-to-many. See docs/refactor-v2-plan.md
§4.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Team(BaseModel):
    id: str
    name: str
    project_id: str | None = None
    description: str = ""
    created_at: datetime
    updated_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_id: str | None = None
    description: str = Field(default="", max_length=4000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Team name cannot be blank.")
        return stripped


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    project_id: str | None = None
    description: str | None = Field(default=None, max_length=4000)
