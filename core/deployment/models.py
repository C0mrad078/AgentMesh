from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.utils.time import utc_now

EnvironmentName = Literal["development", "staging", "production"]
Provider = Literal["github_actions"]
ReleaseStatus = Literal[
    "draft", "ready_for_predeploy", "predeploy_running", "predeploy_failed",
    "awaiting_development_approval", "deploying_development", "development_verification",
    "development_failed", "development_ready", "awaiting_staging_approval", "deploying_staging",
    "staging_verification", "staging_failed", "staging_ready", "awaiting_production_approval",
    "deploying_production", "production_verification", "production_failed", "production_healthy",
    "rollback_proposed", "awaiting_rollback_approval", "rolling_back", "rollback_verification",
    "rolled_back", "rollback_failed", "blocked", "cancelled",
]


class DeploymentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(default_factory=lambda: str(uuid4()))


class ApprovalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    required_roles: list[str] = Field(default_factory=list)
    min_approvals: int = Field(default=1, ge=0)
    allow_same_author: bool = False
    reinforced_production: bool = False


class DeploymentEnvironment(DeploymentRecord):
    project_id: str
    name: EnvironmentName
    display_name: str
    provider: Provider = "github_actions"
    remote_identifier: str
    allowed_branches_or_shas: list[str] = Field(default_factory=lambda: ["main"])
    health_check_profile_id: str | None = None
    approval_policy: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    concurrency_limit: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=3600, ge=1)
    rollback_strategy: Literal["previous_healthy", "specific_release"] = "previous_healthy"
    observed_state: Literal["idle", "deploying", "verifying", "healthy", "unhealthy", "blocked"] = "idle"
    current_release_id: str | None = None
    current_release_sha: str | None = None
    last_healthy_release_id: str | None = None
    last_healthy_release_sha: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DeploymentBinding(DeploymentRecord):
    project_id: str
    environment_id: str
    provider: Provider = "github_actions"
    remote_url: str
    repo_name: str
    target_branch: str = "main"
    workflow_file: str
    environment_name: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReleaseCandidate(DeploymentRecord):
    project_id: str
    delivery_candidate_id: str
    delivery_snapshot_id: str
    version: int = Field(default=1, ge=1)
    target_sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    source_branch: str = "main"
    status: ReleaseStatus = "draft"
    artifacts_manifest: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    created_by: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReleaseSnapshot(DeploymentRecord):
    release_candidate_id: str
    version: int = Field(ge=1)
    target_sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    artifacts_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    manifest: dict[str, Any] = Field(default_factory=dict)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class DeploymentRun(DeploymentRecord):
    project_id: str
    release_candidate_id: str
    environment_id: str
    environment_name: EnvironmentName
    target_sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    status: Literal["pending", "leased", "in_flight", "verifying", "succeeded", "failed", "cancelled", "blocked"] = "pending"
    idempotency_key: str = Field(min_length=1)
    current_attempt_number: int = Field(default=1, ge=1)
    initiated_by: str = Field(min_length=1)
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DeploymentAttempt(DeploymentRecord):
    deployment_run_id: str
    attempt_number: int = Field(ge=1)
    status: Literal["running", "succeeded", "failed", "cancelled"] = "running"
    provider_run_id: str | None = None
    provider_run_url: str | None = None
    failure_reason: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class EnvironmentLease(DeploymentRecord):
    environment_id: str
    lease_token: str = Field(default_factory=lambda: str(uuid4()))
    held_by_run_id: str
    status: Literal["active", "expired", "released"] = "active"
    expires_at: datetime
    acquired_at: datetime = Field(default_factory=utc_now)
    released_at: datetime | None = None


class DeploymentOperation(DeploymentRecord):
    deployment_run_id: str
    idempotency_key: str = Field(min_length=1)
    operation_type: Literal["dispatch_workflow", "cancel_workflow", "poll_workflow", "execute_rollback"]
    provider: str
    remote_id: str | None = None
    status: Literal["pending", "in_flight", "succeeded", "failed"] = "pending"
    request_payload_sanitized: dict[str, Any] = Field(default_factory=dict)
    response_payload_sanitized: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DeploymentLog(DeploymentRecord):
    deployment_run_id: str
    attempt_number: int = Field(ge=1)
    log_level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    message_sanitized: str
    source: str
    timestamp: datetime = Field(default_factory=utc_now)


class PromotionRequest(DeploymentRecord):
    project_id: str
    release_candidate_id: str
    from_environment_id: str
    to_environment_id: str
    status: Literal["pending", "approved", "rejected", "in_progress", "completed", "cancelled"] = "pending"
    requested_by: str
    target_sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DeploymentApproval(DeploymentRecord):
    project_id: str
    release_candidate_id: str
    deployment_run_id: str | None = None
    environment_id: str
    action: Literal["deploy_development", "deploy_staging", "deploy_production", "rollback_production", "promote"]
    status: Literal["pending", "approved", "rejected"] = "pending"
    actor_id: str
    actor_role: str
    comment: str | None = None
    approved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class DeploymentIncident(DeploymentRecord):
    deployment_run_id: str
    environment_id: str
    severity: Literal["P0", "P1", "P2", "P3"]
    title: str
    description: str
    root_cause: str | None = None
    suggested_action: str
    is_resolved: bool = False
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class HealthCheckProfile(DeploymentRecord):
    project_id: str
    environment_id: str
    name: str
    check_type: Literal["http_get", "local_command"]
    target: str
    expected_status: int | None = 200
    expected_body_substring: str | None = None
    timeout_seconds: int = Field(default=10, ge=1)
    max_retries: int = Field(default=3, ge=0)
    retry_interval_seconds: int = Field(default=5, ge=0)
    observation_period_seconds: int = Field(default=30, ge=0)
    headers_secret_ref: str | None = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class HealthCheckResult(DeploymentRecord):
    deployment_run_id: str
    profile_id: str
    status: Literal["passed", "failed", "timed_out"]
    status_code: int | None = None
    response_time_ms: int | None = None
    details_sanitized: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)


class DeploymentRollbackPlan(DeploymentRecord):
    project_id: str
    deployment_run_id: str
    environment_id: str
    current_release_id: str
    target_release_id: str
    target_sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    rollback_strategy: Literal["previous_healthy", "specific_release"]
    impact_summary: str
    risk_assessment: str
    status: Literal["proposed", "approved", "rejected", "executing", "completed", "failed"] = "proposed"
    created_at: datetime = Field(default_factory=utc_now)


class DeploymentRollbackExecution(DeploymentRecord):
    rollback_plan_id: str
    status: Literal["running", "succeeded", "failed"] = "running"
    initiated_by: str
    provider_run_id: str | None = None
    provider_run_url: str | None = None
    post_verification_status: Literal["pending", "passed", "failed"] = "pending"
    error_message: str | None = None
    executed_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class DeploymentPhaseTelemetry(DeploymentRecord):
    deployment_run_id: str
    phase_name: str
    duration_ms: int | None = Field(default=None, ge=0)
    queue_wait_ms: int | None = Field(default=None, ge=0)
    human_wait_ms: int | None = Field(default=None, ge=0)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None
    status: str


class DeploymentInternalStep(DeploymentRecord):
    deployment_run_id: str
    step_name: str
    status: Literal["pending", "in_progress", "completed", "failed", "skipped"] = "pending"
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeploymentRecoveryState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    is_blocked: bool
    recovery_reason: str | None = None
    suggested_action: str | None = None
    active_leases: list[dict[str, str]] = Field(default_factory=list)
    reconciled_runs_count: int = 0
