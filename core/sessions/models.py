"""Session domain models (Refactor V2, Phase 1).

A `Session` is one real, continuous execution turn: one agent, running
through one provider/backend/(optional) account combination, optionally
against one task and inside one worktree. It is *not* the same thing as
`core.orchestrator.models.RoutingDecision`/the `executions` table -- those
are the DAG-run bookkeeping for a single `Task`'s steps, which continues to
exist unchanged. How the two reconcile (does one Session wrap many
`executions` rows, or vice versa) is a Phase 2/3 wiring decision; Phase 1
only defines and persists the Session shape itself, per
docs/refactor-v2-plan.md §4.

`external_session_id` holds whatever identifier the underlying CLI itself
uses for the run (e.g. a Claude Code session id), when it exposes one --
`None` when the backend doesn't support that concept, never fabricated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.runtime.execution_backend import ExecutionBackendType


class SessionStatus(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    WORKING = "working"
    WAITING = "waiting"
    PAUSED = "paused"
    IDLE = "idle"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


TERMINAL_SESSION_STATUSES = frozenset(
    {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.INTERRUPTED, SessionStatus.CANCELLED}
)


class Session(BaseModel):
    id: str
    agent_id: str
    project_id: str
    provider_id: str
    backend_type: ExecutionBackendType
    account_id: str | None = None
    task_id: str | None = None
    worktree_id: str | None = None
    external_session_id: str | None = None
    status: SessionStatus = SessionStatus.CREATED
    started_at: datetime | None = None
    updated_at: datetime
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SessionCreate(BaseModel):
    agent_id: str
    project_id: str
    provider_id: str
    backend_type: ExecutionBackendType
    account_id: str | None = None
    task_id: str | None = None
    worktree_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
