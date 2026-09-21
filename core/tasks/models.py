"""Task domain models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.PARTIAL, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


class TaskMode(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    PIPELINE = "pipeline"
    DEBATE = "debate"
    CONSENSUS = "consensus"


class Task(BaseModel):
    id: str
    project_id: str
    conversation_id: str | None = None
    title: str
    description: str = ""
    mode: TaskMode = TaskMode.AUTOMATIC
    status: TaskStatus = TaskStatus.QUEUED
    input: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    # Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): explicit
    # assignment, all nullable -- today's automatic/DAG-routed tasks leave
    # these unset and are entirely unaffected. The DAG-level `PlanStep`/
    # `Router` assignment system is separate and untouched by these.
    assigned_agent_id: str | None = None
    assigned_team_id: str | None = None
    session_id: str | None = None
    waiting_reason: str = ""


class TaskCreate(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=8000)
    mode: TaskMode = TaskMode.AUTOMATIC
    conversation_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    assigned_agent_id: str | None = None
    assigned_team_id: str | None = None
