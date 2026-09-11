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
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
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


class TaskCreate(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=8000)
    mode: TaskMode = TaskMode.AUTOMATIC
    conversation_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
