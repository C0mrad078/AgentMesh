"""Worktree domain models (Refactor V2, Phase 1).

A `Worktree` row records one real `git worktree` checkout under a
project's `.agentmash/worktrees/` directory. This module only defines the
persisted shape; actually creating/cleaning up a `git worktree` on disk is
`WorktreeManager`'s job (Phase 4) -- not implemented here, so nothing in
Phase 1 claims a worktree exists on disk just because a row exists for it.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class WorktreeStatus(str, Enum):
    ACTIVE = "active"
    CLEANED = "cleaned"
    CONFLICT = "conflict"


class Worktree(BaseModel):
    id: str
    project_id: str
    branch_name: str
    path: str
    status: WorktreeStatus = WorktreeStatus.ACTIVE
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None = None


class WorktreeCreate(BaseModel):
    project_id: str
    branch_name: str = Field(min_length=1, max_length=300)
    path: str = Field(min_length=1)
