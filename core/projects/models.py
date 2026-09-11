"""Project domain models.

A project is the top-level unit of work in the Orquestrador. Everything the
system will eventually attach to a unit of work -- memory, agents, files,
git state, conversation history, project-specific rules -- hangs off a
project id. This stage only persists the base fields; `config` is an open
JSON bag reserved for the settings future stages will need (git integration
toggles, per-project agent overrides, learning preferences, etc.) so those
can be added without a schema migration.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Project(BaseModel):
    id: str
    name: str
    description: str = ""
    workspace_path: str | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    workspace_path: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Project name cannot be blank.")
        return stripped


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    workspace_path: str | None = None
    status: ProjectStatus | None = None
    config: dict[str, Any] | None = None
