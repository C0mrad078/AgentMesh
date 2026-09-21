from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.utils.time import utc_now

DeliveryStatus = Literal[
    "draft",
    "preflight_running",
    "preflight_failed",
    "awaiting_remote_approval",
    "pushing",
    "pr_open",
    "ci_running",
    "ci_failed",
    "fixing",
    "awaiting_merge_approval",
    "merging",
    "merged",
    "post_merge_failed",
    "rollback_proposed",
    "rolled_back",
    "rejected",
    "cancelled",
    "blocked",
]
Action = Literal["push", "pr_create", "pr_update", "merge", "rollback"]
Phase = Literal[
    "preflight",
    "remote_push",
    "pr_cycle",
    "ci_monitoring",
    "ci_correction",
    "merge",
    "post_merge",
    "rollback",
]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(default_factory=lambda: str(uuid4()))


class DeliveryCandidate(Record):
    mission_id: str
    project_id: str
    version: int = Field(ge=1)
    status: DeliveryStatus = "draft"
    current_snapshot_id: str
    target_remote_binding_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DeliverySnapshot(Record):
    candidate_id: str
    version: int = Field(ge=1)
    mission_id: str
    project_id: str
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    integration_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    diff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    commits: list[dict[str, Any]]
    diff_stat: dict[str, int]
    tasks_summary: list[dict[str, Any]]
    reviews_summary: list[dict[str, Any]]
    resolved_conflicts_summary: list[dict[str, Any]]
    quality_gates_summary: list[dict[str, Any]]
    known_risks: list[str]
    diff_sanitized: str | None = None
    agents_summary: list[dict[str, Any]] = Field(default_factory=list)
    sessions_summary: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_summary: list[dict[str, Any]] = Field(default_factory=list)
    integration_path: str | None = None
    schema_version: Literal[1] = 1
    created_at: datetime = Field(default_factory=utc_now)


class RemoteRepositoryBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    provider: Literal["git", "github"] = "github"
    remote_name: str = "origin"
    remote_url: str
    owner: str | None = None
    repository: str | None = None
    target_branch: str = "main"
    default_merge_method: Literal["squash", "merge", "rebase"] = "squash"


class RemoteRepositoryBinding(Record):
    project_id: str
    provider: Literal["git", "github"]
    remote_name: str = "origin"
    remote_url_sanitized: str
    owner: str | None = None
    repository: str | None = None
    target_branch: str = "main"
    auth_detected: bool = False
    auth_type: Literal["ssh", "gh_cli", "token_keychain", "none"] = "none"
    permissions: list[str] = Field(default_factory=list)
    branch_protections: dict[str, Any] = Field(default_factory=dict)
    default_merge_method: Literal["squash", "merge", "rebase"] = "squash"
    last_verified_at: datetime | None = None


class PreflightReport(Record):
    candidate_id: str
    version: int
    status: Literal["passed", "failed"]
    remote_reachable: bool
    base_up_to_date: bool
    clean_integration_tree: bool
    quality_gate_passed: bool
    secret_scan_passed: bool
    secret_findings: list[dict[str, Any]] = Field(default_factory=list)
    large_binary_findings: list[dict[str, Any]] = Field(default_factory=list)
    migration_lockfile_check: dict[str, str]
    risk_level: Literal["low", "medium", "high", "critical"]
    blocking_reasons: list[str] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=utc_now)


class DeliveryApproval(Record):
    candidate_id: str
    version: int
    action: Action
    decision: Literal["approved", "rejected"]
    actor: str = Field(min_length=1, max_length=200)
    target_sha: str
    reason: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class RemoteOperation(Record):
    candidate_id: str
    operation_type: Action
    idempotency_key: str = Field(min_length=1, max_length=200)
    payload_sanitized: dict[str, Any]
    approved_by: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    attempts: int = 0
    result: dict[str, Any] | None = None
    error_sanitized: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PullRequestRecord(Record):
    candidate_id: str
    remote_binding_id: str
    pr_number: int | None = None
    pr_id: str | None = None
    pr_url: str | None = None
    title: str
    body: str
    delivery_branch: str
    target_branch: str
    head_sha: str
    base_sha: str
    state: Literal["open", "closed", "merged"] = "open"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CIWorkflowRun(Record):
    pr_record_id: str
    commit_sha: str
    name: str
    status: Literal["queued", "in_progress", "completed"]
    conclusion: Literal["success", "failure", "cancelled", "timed_out", "neutral", "unknown"]
    run_url: str | None = None
    logs_sanitized: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CICheck(CIWorkflowRun):
    pass


class CIFailureFinding(Record):
    check_id: str
    candidate_id: str
    classification: Literal[
        "test_failure", "lint_error", "type_error", "build_failure", "timeout", "infra_error"
    ]
    assigned_task_id: str | None = None
    assigned_agent_id: str | None = None
    worktree_path: str | None = None
    iteration: int = 0
    status: Literal["analyzing", "fixing", "reviewed", "gated", "ready_for_push", "exhausted"] = (
        "analyzing"
    )


class PostMergeVerification(Record):
    candidate_id: str
    target_sha_observed: str
    checks_run: list[dict[str, Any]]
    status: Literal["passed", "failed"]
    verified_at: datetime = Field(default_factory=utc_now)


class RollbackPlan(Record):
    candidate_id: str
    merge_commit_sha: str
    strategy: Literal["revert_pr", "revert_commit"] = "revert_pr"
    revert_branch: str
    revert_pr_url: str | None = None
    status: Literal["proposed", "awaiting_approval", "executing", "completed", "failed"] = (
        "proposed"
    )
    created_at: datetime = Field(default_factory=utc_now)


class PhaseTelemetry(Record):
    task_id: str | None = None
    queue_wait_ms: int | None = Field(default=None, ge=0)
    human_wait_ms: int | None = Field(default=None, ge=0)
    mission_id: str
    candidate_id: str | None = None
    phase: Phase
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    duration_ms: int | None = None
    agent_id: str | None = None
    session_id: str | None = None
    provider_id: str | None = None
    retries: int = 0
    token_usage: dict[str, int] | Literal["unknown"] = "unknown"
    cost_usd: float | Literal["unknown"] = "unknown"
    timeout_seconds: int | None = None
    outcome: Literal["success", "failure", "cancelled", "blocked"]
    error_sanitized: str | None = None
    human_touch_count: int = 0


class InternalStep(Record):
    candidate_id: str
    name: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
