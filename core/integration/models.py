from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConflictStatus = Literal[
    "detected",
    "awaiting_analysis",
    "analyzing",
    "awaiting_context",
    "resolution_proposed",
    "reviewing",
    "changes_requested",
    "testing",
    "awaiting_human_approval",
    "resolved",
    "rejected",
    "blocked",
    "cancelled",
]
ConflictClassification = Literal[
    "textual",
    "rename_delete",
    "add_add",
    "binary",
    "migration_schema",
    "lockfile",
    "generated",
    "api_contract",
    "semantic",
    "unknown",
]


class ConflictFile(BaseModel):
    id: str
    conflict_id: str
    path: str
    classification: ConflictClassification
    base: str = ""
    ours: str = ""
    theirs: str = ""
    stages: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class IntegrationConflict(BaseModel):
    id: str
    mission_id: str
    integration_attempt_id: str | None = None
    status: ConflictStatus = "detected"
    classification: ConflictClassification = "unknown"
    base_sha: str
    ours_sha: str
    theirs_sha: str
    integration_head: str
    resolution_worktree_id: str | None = None
    integrator_session_id: str | None = None
    reviewer_session_id: str | None = None
    data: dict = Field(default_factory=dict)
    files: list[ConflictFile] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ResolutionAttempt(BaseModel):
    id: str
    conflict_id: str
    attempt_no: int
    status: str
    worktree_id: str | None = None
    integrator_session_id: str | None = None
    proposal_artifact_id: str | None = None
    commit_sha: str | None = None
    strategy: str = ""
    data: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    resolution_path: str | None = None
    resolution_branch: str | None = None


class ResolutionReview(BaseModel):
    id: str
    conflict_id: str
    attempt_id: str
    reviewer_session_id: str | None = None
    verdict: Literal["approved", "changes_requested", "blocked", "human_input_required"]
    findings: list[dict] = Field(default_factory=list)
    created_at: datetime


class ResolutionDecision(BaseModel):
    id: str
    conflict_id: str
    attempt_id: str | None = None
    decision: Literal["approved", "rejected", "corrections_requested", "waiting"]
    rationale: str = ""
    actor_session_id: str | None = None
    created_at: datetime


class IntegrationProposal(BaseModel):
    strategy: str = Field(min_length=1, max_length=12000)
    files: list[str] = Field(default_factory=list, max_length=100)
    decisions: list[str] = Field(default_factory=list, max_length=100)
    preserved_behaviors: list[str] = Field(default_factory=list, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=50)
    tests: list[list[str]] = Field(default_factory=list, max_length=20)
    question: str | None = None


class QualityGateDefinition(BaseModel):
    id: str
    name: str
    argv: list[str] = Field(min_length=1, max_length=32)
    cwd: str = "."
    kind: Literal["test", "lint", "typecheck", "build", "migration", "security", "custom"] = (
        "custom"
    )
    required: bool = True
    timeout_seconds: int = Field(default=600, ge=1, le=7200)
    order: int = 0
    enabled: bool = True
    retry_limit: int = Field(default=0, ge=0, le=3)
    log_limit: int = Field(default=20000, ge=1000, le=200000)
    source: Literal["detected", "user", "project_default"] = "user"
    approval_required: bool = False


class QualityGateProfile(BaseModel):
    id: str
    project_id: str
    name: str
    is_default: bool = False
    gates: list[QualityGateDefinition] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


def classify_conflict(
    path: str, *, status: str = "UU", binary: bool = False
) -> ConflictClassification:
    """Conservative, deterministic conflict classification used before an Agent
    is allowed to propose a resolution.  It never claims a semantic conflict
    is safe merely because Git accepted a merge."""
    lower = path.lower()
    if binary:
        return "binary"
    if "lock" in lower or lower.endswith((".lock", "lock.json")):
        return "lockfile"
    if (
        "migration" in lower
        or "/migrations/" in lower
        or lower.endswith(("schema.sql", "schema.json"))
    ):
        return "migration_schema"
    if lower.endswith((".generated.ts", ".generated.py", ".snap")):
        return "generated"
    if (
        lower.endswith((".json", ".yaml", ".yml", ".proto", ".graphql"))
        or "contract" in lower
        or "api" in lower
    ):
        return "api_contract"
    if status in {"AA"}:
        return "add_add"
    if status in {"UD", "DU", "DD"}:
        return "rename_delete"
    return "textual"
