from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class IsolationMode(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"


class ForecastLevel(str, Enum):
    NONE = "none"
    POSSIBLE = "possible"
    LIKELY = "likely"
    CONFIRMED = "confirmed"


class ParallelTaskSpec(BaseModel):
    key: str
    isolation: IsolationMode = IsolationMode.WRITE
    expected_paths: list[str] = Field(default_factory=list, max_length=100)
    validation_commands: list[list[str]] = Field(default_factory=list, max_length=10)
    risk: Literal["low", "medium", "high", "critical"] = "medium"
    review_policy: Literal["required", "optional"] = "required"
    expected_artifacts: list[str] = Field(default_factory=list, max_length=20)


class WorktreeLease(BaseModel):
    id: str
    mission_id: str
    task_id: str
    session_id: str | None = None
    project_id: str
    workspace_root: str
    path: str
    branch_name: str
    base_sha: str
    head_sha: str | None = None
    status: Literal["creating", "active", "orphaned", "integrated", "conflict", "cleaned"]
    created_at: datetime
    updated_at: datetime
    last_error: str = ""


class ConcurrencyLease(BaseModel):
    id: str
    mission_id: str
    task_id: str | None = None
    session_id: str | None = None
    project_id: str
    provider: str
    runtime_binding_id: str | None = None
    account_id: str | None = None
    expires_at: datetime
    created_at: datetime


class ConflictForecast(BaseModel):
    id: str
    mission_id: str
    task_id: str
    other_task_id: str | None = None
    level: ForecastLevel
    paths: list[str] = Field(default_factory=list)
    reason: str
    created_at: datetime


class IntegrationAttempt(BaseModel):
    id: str
    mission_id: str
    task_id: str
    integration_branch: str
    source_branch: str
    base_sha: str
    result: Literal["started", "integrated", "conflict", "failed", "skipped"]
    commit_sha: str | None = None
    message: str = ""
    created_at: datetime


class QualityGateRun(BaseModel):
    id: str
    mission_id: str
    task_id: str | None = None
    name: str
    command: list[str]
    exit_code: int
    duration_ms: int
    summary: str
    passed: bool
    created_at: datetime


class HumanApproval(BaseModel):
    id: str
    mission_id: str
    decision: Literal["approved", "corrections_requested", "rejected", "waiting"]
    rationale: str
    created_at: datetime
