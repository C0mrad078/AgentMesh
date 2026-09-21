# AgentMash V3 — Milestone 5 Shared Contract: Deployment & Release Control Center

This document establishes the binding architectural contract, domain models, state machine, bridge protocol, file ownership boundaries, security invariants, and acceptance criteria for **Milestone 5 (Deployment & Release Control Center)**.

---

## 1. Architectural Mission & Objectives

The purpose of Milestone 5 is to transition an approved and merged `DeliveryCandidate` (from Milestone 4) into a controlled, observable, recoverable, and secure deployment across distinct target environments:

$$\text{development} \longrightarrow \text{staging} \longrightarrow \text{production}$$

### Key Architectural Invariants & Guarantees:
1. **Origin in Merged Delivery Candidate**: Every `ReleaseCandidate` must originate from a verified, merged `DeliveryCandidate` and reference the concrete commit SHA verified present in the remote target branch (`main`).
2. **Frozen Immutability**: A `ReleaseCandidate` possesses an immutable `ReleaseSnapshot` recording manifest, artifacts, hashes, quality gate evidence, source commits, and creator identity. Any modification requires an incremental version bump.
3. **Environment Isolation & Concurrency Control**: Environments (`development`, `staging`, `production`) are strictly isolated with exclusive locks (`EnvironmentLease`). Only one active deployment run may hold a lease for an environment at any given time.
4. **Mandatory Human Approvals & Segregation of Duties**:
   - Staging deployments require explicit human approval.
   - Production deployments require reinforced human approval.
   - Production rollback requires dedicated separate human approval.
   - **Enforced Separation of Duties**: The same actor cannot produce, review, and approve a production deployment alone.
5. **Identical SHA Promotion**: Promotion across environments (`dev -> staging -> prod`) must promote the **exact same commit SHA / artifact digest**. Silent rebuilding of releases or promoting modified SHAs is strictly prohibited.
6. **Provider Abstraction**: Initial support uses GitHub Actions (`workflow_dispatch`), monitoring workflows, jobs, and commit statuses. The design is modular to allow future providers without domain core changes.
7. **Safe Rollback**: Rollbacks must target a known healthy historical release, persist an impact plan, require human approval for production, execute via the provider, and verify health post-rollback before declaring success.
8. **Real Health Checks**: Automated health validation (HTTP GET, local commands) with configurable timeouts, retries, observation intervals, and secret masking.
9. **Crash Recovery & Reconciler**: Upon system restart, in-flight runs reconcile status with remote providers, expired leases are reclaimed or alerted, and unknown states default to `blocked` with clear user-facing `suggested_action`.
10. **Zero Secrets in Persistence or Logs**: Authorization tokens and private credentials must never appear in SQLite, JSON payloads, URLs, bridge events, or frontend views.

---

## 2. Domain Models & Entities

### 2.1 Deployment Environments & Bindings
- **`DeploymentEnvironment`**:
  - `id`: string (UUID)
  - `project_id`: string
  - `name`: `Literal["development", "staging", "production"]`
  - `display_name`: string
  - `provider`: `Literal["github_actions"]`
  - `remote_identifier`: string (e.g. GitHub environment name or repo/env)
  - `allowed_branches_or_shas`: list of string (e.g. `["main"]`)
  - `health_check_profile_id`: string | null
  - `approval_policy`: `{ required_roles: list[str], min_approvals: int, allow_same_author: bool, reinforced_production: bool }`
  - `concurrency_limit`: int (default `1`)
  - `timeout_seconds`: int (default `3600`)
  - `rollback_strategy`: `Literal["previous_healthy", "specific_release"]`
  - `observed_state`: `Literal["idle", "deploying", "verifying", "healthy", "unhealthy", "blocked"]`
  - `current_release_id`: string | null
  - `current_release_sha`: string | null
  - `last_healthy_release_id`: string | null
  - `last_healthy_release_sha`: string | null
  - `created_at`: datetime (UTC ISO8601)
  - `updated_at`: datetime (UTC ISO8601)

- **`DeploymentBinding`**:
  - `id`: string (UUID)
  - `project_id`: string
  - `environment_id`: string
  - `provider`: string (`"github_actions"`)
  - `remote_url`: string (sanitized, no credentials)
  - `repo_name`: string
  - `target_branch`: string
  - `workflow_file`: string (e.g. `"deploy.yml"`)
  - `environment_name`: string
  - `is_active`: bool
  - `created_at`: datetime (UTC ISO8601)
  - `updated_at`: datetime (UTC ISO8601)

### 2.2 Release Candidate & Snapshot
- **`ReleaseCandidate`**:
  - `id`: string (UUID)
  - `project_id`: string
  - `delivery_candidate_id`: string (FK to Milestone 4 `DeliveryCandidate`)
  - `delivery_snapshot_id`: string
  - `version`: int (starts at 1, increments on new releases for project)
  - `target_sha`: string (40-char git commit SHA verified on target branch)
  - `source_branch`: string
  - `status`: `ReleaseStatus` (state machine state)
  - `artifacts_manifest`: dict (JSON string in DB)
  - `risk_level`: `Literal["low", "medium", "high", "critical"]`
  - `created_by`: string
  - `created_at`: datetime (UTC ISO8601)
  - `updated_at`: datetime (UTC ISO8601)

- **`ReleaseSnapshot`**:
  - `id`: string (UUID)
  - `release_candidate_id`: string
  - `version`: int
  - `target_sha`: string
  - `artifacts_hash`: string (SHA-256)
  - `manifest`: dict (sanitized)
  - `evidence_summary`: `{ delivery_candidate_id, delivery_gates, test_pass_count, merged_at }`
  - `created_at`: datetime (UTC ISO8601)

### 2.3 Deployment Execution & Concurrency
- **`DeploymentRun`**:
  - `id`: string (UUID)
  - `project_id`: string
  - `release_candidate_id`: string
  - `environment_id`: string
  - `environment_name`: string
  - `target_sha`: string
  - `status`: `Literal["pending", "leased", "in_flight", "verifying", "succeeded", "failed", "cancelled", "blocked"]`
  - `idempotency_key`: string
  - `current_attempt_number`: int (default 1)
  - `initiated_by`: string
  - `error_message`: string | null
  - `started_at`: datetime (UTC ISO8601) | null
  - `completed_at`: datetime (UTC ISO8601) | null
  - `created_at`: datetime (UTC ISO8601)
  - `updated_at`: datetime (UTC ISO8601)

- **`DeploymentAttempt`**:
  - `id`: string (UUID)
  - `deployment_run_id`: string
  - `attempt_number`: int
  - `status`: `Literal["running", "succeeded", "failed", "cancelled"]`
  - `provider_run_id`: string | null
  - `provider_run_url`: string | null
  - `failure_reason`: string | null
  - `started_at`: datetime (UTC ISO8601)
  - `completed_at`: datetime (UTC ISO8601) | null

- **`EnvironmentLease`**:
  - `id`: string (UUID)
  - `environment_id`: string
  - `lease_token`: string (UUID)
  - `held_by_run_id`: string
  - `status`: `Literal["active", "expired", "released"]`
  - `expires_at`: datetime (UTC ISO8601)
  - `acquired_at`: datetime (UTC ISO8601)
  - `released_at`: datetime (UTC ISO8601) | null

- **`DeploymentOperation`**:
  - `id`: string (UUID)
  - `deployment_run_id`: string
  - `idempotency_key`: string
  - `operation_type`: `Literal["dispatch_workflow", "cancel_workflow", "poll_workflow", "execute_rollback"]`
  - `provider`: string
  - `remote_id`: string | null
  - `status`: `Literal["pending", "in_flight", "succeeded", "failed"]`
  - `request_payload_sanitized`: dict
  - `response_payload_sanitized`: dict
  - `created_at`: datetime (UTC ISO8601)
  - `updated_at`: datetime (UTC ISO8601)

- **`DeploymentLog`**:
  - `id`: string (UUID)
  - `deployment_run_id`: string
  - `attempt_number`: int
  - `log_level`: `Literal["DEBUG", "INFO", "WARN", "ERROR"]`
  - `message_sanitized`: string
  - `source`: string
  - `timestamp`: datetime (UTC ISO8601)

### 2.4 Governance, Promotion, Approvals & Incidents
- **`PromotionRequest`**:
  - `id`: string (UUID)
  - `project_id`: string
  - `release_candidate_id`: string
  - `from_environment_id`: string
  - `to_environment_id`: string
  - `status`: `Literal["pending", "approved", "rejected", "in_progress", "completed", "cancelled"]`
  - `requested_by`: string
  - `target_sha`: string
  - `created_at`: datetime (UTC ISO8601)
  - `updated_at`: datetime (UTC ISO8601)

- **`DeploymentApproval`**:
  - `id`: string (UUID)
  - `project_id`: string
  - `release_candidate_id`: string
  - `deployment_run_id`: string | null
  - `environment_id`: string
  - `action`: `Literal["deploy_development", "deploy_staging", "deploy_production", "rollback_production", "promote"]`
  - `status`: `Literal["pending", "approved", "rejected"]`
  - `actor_id`: string
  - `actor_role`: string
  - `comment`: string | null
  - `approved_at`: datetime (UTC ISO8601) | null
  - `metadata`: dict

- **`DeploymentIncident`**:
  - `id`: string (UUID)
  - `deployment_run_id`: string
  - `environment_id`: string
  - `severity`: `Literal["P0", "P1", "P2", "P3"]`
  - `title`: string
  - `description`: string
  - `root_cause`: string | null
  - `suggested_action`: string
  - `is_resolved`: bool
  - `resolved_at`: datetime (UTC ISO8601) | null
  - `created_at`: datetime (UTC ISO8601)

### 2.5 Health Checks & Verification
- **`HealthCheckProfile`**:
  - `id`: string (UUID)
  - `project_id`: string
  - `environment_id`: string
  - `name`: string
  - `check_type`: `Literal["http_get", "local_command"]`
  - `target`: string (URL or executable command)
  - `expected_status`: int | null (e.g. 200)
  - `expected_body_substring`: string | null
  - `timeout_seconds`: int (default 10)
  - `max_retries`: int (default 3)
  - `retry_interval_seconds`: int (default 5)
  - `observation_period_seconds`: int (default 30)
  - `headers_secret_ref`: string | null (name of secret reference, never raw credentials)
  - `is_active`: bool
  - `created_at`: datetime (UTC ISO8601)
  - `updated_at`: datetime (UTC ISO8601)

- **`HealthCheckResult`**:
  - `id`: string (UUID)
  - `deployment_run_id`: string
  - `profile_id`: string
  - `status`: `Literal["passed", "failed", "timed_out"]`
  - `status_code`: int | null
  - `response_time_ms`: int | null
  - `details_sanitized`: dict
  - `error_message`: string | null
  - `checked_at`: datetime (UTC ISO8601)

### 2.6 Rollback Planning & Execution
- **`DeploymentRollbackPlan`**:
  - `id`: string (UUID)
  - `project_id`: string
  - `deployment_run_id`: string
  - `environment_id`: string
  - `current_release_id`: string
  - `target_release_id`: string
  - `target_sha`: string
  - `rollback_strategy`: `Literal["previous_healthy", "specific_release"]`
  - `impact_summary`: string
  - `risk_assessment`: string
  - `status`: `Literal["proposed", "approved", "rejected", "executing", "completed", "failed"]`
  - `created_at`: datetime (UTC ISO8601)

- **`DeploymentRollbackExecution`**:
  - `id`: string (UUID)
  - `rollback_plan_id`: string
  - `status`: `Literal["running", "succeeded", "failed"]`
  - `initiated_by`: string
  - `provider_run_id`: string | null
  - `provider_run_url`: string | null
  - `post_verification_status`: `Literal["pending", "passed", "failed"]`
  - `error_message`: string | null
  - `executed_at`: datetime (UTC ISO8601)
  - `completed_at`: datetime (UTC ISO8601) | null

### 2.7 Telemetry & Internal Steps
- **`DeploymentPhaseTelemetry`**:
  - `id`: string (UUID)
  - `deployment_run_id`: string
  - `phase_name`: string
  - `duration_ms`: int | null (strictly null if unmeasured, never fake 0)
  - `queue_wait_ms`: int | null
  - `human_wait_ms`: int | null
  - `started_at`: datetime (UTC ISO8601)
  - `ended_at`: datetime (UTC ISO8601) | null
  - `status`: string

- **`DeploymentInternalStep`**:
  - `id`: string (UUID)
  - `deployment_run_id`: string
  - `step_name`: string
  - `status`: `Literal["pending", "in_progress", "completed", "failed", "skipped"]`
  - `started_at`: datetime (UTC ISO8601)
  - `completed_at`: datetime (UTC ISO8601) | null
  - `metadata`: dict

---

## 3. Deployment Lifecycle & State Machine

The release candidate navigates through 27 formal lifecycle states:

```
[draft] ──> [ready_for_predeploy] ──> [predeploy_running]
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
              [predeploy_failed]                    [awaiting_development_approval]
                                                                   │
                                                                   ▼
                                                         [deploying_development]
                                                                   │
                                                                   ▼
                                                       [development_verification]
                                                                   │
                                           ┌───────────────────────┴───────────────────────┐
                                           ▼                                               ▼
                                 [development_failed]                             [development_ready]
                                                                                           │
                                                                                           ▼
                                                                              [awaiting_staging_approval]
                                                                                           │
                                                                                           ▼
                                                                                   [deploying_staging]
                                                                                           │
                                                                                           ▼
                                                                                  [staging_verification]
                                                                                           │
                                                                   ┌───────────────────────┴───────────────────────┐
                                                                   ▼                                               ▼
                                                            [staging_failed]                                [staging_ready]
                                                                                                                   │
                                                                                                                   ▼
                                                                                                     [awaiting_production_approval]
                                                                                                                   │
                                                                                                                   ▼
                                                                                                          [deploying_production]
                                                                                                                   │
                                                                                                                   ▼
                                                                                                         [production_verification]
                                                                                                                   │
                                                                           ┌───────────────────────────────────────┴───────────────────────────────────────┐
                                                                           ▼                                                                               ▼
                                                                  [production_failed]                                                              [production_healthy]
                                                                           │                                                                               │
                                                                           └───────────────────────┬───────────────────────────────────────────────────────┘
                                                                                                   ▼
                                                                                          [rollback_proposed]
                                                                                                   │
                                                                                                   ▼
                                                                                      [awaiting_rollback_approval]
                                                                                                   │
                                                                                                   ▼
                                                                                            [rolling_back]
                                                                                                   │
                                                                                                   ▼
                                                                                         [rollback_verification]
                                                                                                   │
                                                                                   ┌───────────────┴───────────────┐
                                                                                   ▼                               ▼
                                                                            [rollback_failed]                [rolled_back]

Special global transitions:
Any active state ──> [blocked] (on lease expiration, missing remote resource, or security breach)
Any pre-execution state ──> [cancelled] (on operator abort)
```

### Complete List of States:
1. `draft`
2. `ready_for_predeploy`
3. `predeploy_running`
4. `predeploy_failed`
5. `awaiting_development_approval`
6. `deploying_development`
7. `development_verification`
8. `development_failed`
9. `development_ready`
10. `awaiting_staging_approval`
11. `deploying_staging`
12. `staging_verification`
13. `staging_failed`
14. `staging_ready`
15. `awaiting_production_approval`
16. `deploying_production`
17. `production_verification`
18. `production_failed`
19. `production_healthy`
20. `rollback_proposed`
21. `awaiting_rollback_approval`
22. `rolling_back`
23. `rollback_verification`
24. `rolled_back`
25. `rollback_failed`
26. `blocked`
27. `cancelled`

---

## 4. Bridge Protocol & Concrete DTO Schemas

The desktop application communicates with the backend daemon via JSON-RPC over the existing stdin/stdout bridge. All 16 commands are mapped to explicit handlers, recorded in the bridge allowlist, and bound to proper timeouts.

### 4.1 Concrete DTO Schemas

```typescript
// Shared Types & DTOs for Milestone 5

export interface DeploymentEnvironmentSummary {
  id: string;
  project_id: string;
  name: 'development' | 'staging' | 'production';
  display_name: string;
  provider: 'github_actions';
  remote_identifier: string;
  observed_state: 'idle' | 'deploying' | 'verifying' | 'healthy' | 'unhealthy' | 'blocked';
  current_release_id: string | null;
  current_release_sha: string | null;
  last_healthy_release_id: string | null;
  last_healthy_release_sha: string | null;
  active_lease_holder: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeploymentEnvironmentDetail {
  environment: DeploymentEnvironmentSummary;
  binding: DeploymentBindingDTO | null;
  health_profile: HealthCheckProfileDTO | null;
  approval_policy: ApprovalPolicyDTO;
  active_run: DeploymentRunSummaryDTO | null;
  recent_runs: DeploymentRunSummaryDTO[];
}

export interface DeploymentBindingInput {
  project_id: string;
  environment_id: string;
  provider: 'github_actions';
  remote_url: string;
  repo_name: string;
  target_branch: string;
  workflow_file: string;
  environment_name: string;
}

export interface ReleaseCandidateSummary {
  id: string;
  project_id: string;
  delivery_candidate_id: string;
  version: number;
  target_sha: string;
  source_branch: string;
  status: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  current_environment: string | null;
  has_pending_approvals: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ReleaseCandidateDetail {
  release_candidate: ReleaseCandidateSummary;
  snapshot: ReleaseSnapshotDTO;
  delivery_candidate_summary: {
    id: string;
    version: number;
    base_sha: string;
    integration_sha: string;
    merged_at: string;
  };
  environments_status: Record<string, {
    status: string;
    deployed_at: string | null;
    is_current: boolean;
    is_healthy: boolean;
  }>;
  approvals: DeploymentApprovalDTO[];
  promotions: PromotionRequestDTO[];
  current_runs: DeploymentRunSummaryDTO[];
  rollback_plan: DeploymentRollbackPlanDTO | null;
  recovery: DeploymentRecoveryStateDTO | null;
  telemetry: DeploymentPhaseTelemetryDTO[];
  internal_steps: DeploymentInternalStepDTO[];
}

export interface DeploymentRunDetail {
  run: DeploymentRunSummaryDTO;
  attempts: DeploymentAttemptDTO[];
  operations: DeploymentOperationDTO[];
  logs: DeploymentLogDTO[];
  health_results: HealthCheckResultDTO[];
  incidents: DeploymentIncidentDTO[];
  telemetry: DeploymentPhaseTelemetryDTO[];
  internal_steps: DeploymentInternalStepDTO[];
}

export interface DeploymentRecoveryStateDTO {
  is_blocked: boolean;
  recovery_reason: string | null;
  suggested_action: string | null;
  active_leases: Array<{ environment_id: string; held_by_run_id: string; expires_at: string }>;
  reconciled_runs_count: number;
}
```

### 4.2 Bridge Commands Summary
| Command Name | Input Payload | Output Payload | Bridge Timeout |
| :--- | :--- | :--- | :--- |
| `deployment.environment.list` | `{ project_id: string }` | `DeploymentEnvironmentSummary[]` | 30s |
| `deployment.environment.get` | `{ project_id: string, environment_id: string }` | `DeploymentEnvironmentDetail` | 30s |
| `deployment.environment.bind` | `DeploymentBindingInput` | `DeploymentBindingDTO` | 30s |
| `deployment.release.create` | `{ project_id: string, delivery_candidate_id: string }` | `ReleaseCandidateDetail` | 30s |
| `deployment.release.get` | `{ project_id: string, release_candidate_id: string }` | `ReleaseCandidateDetail` | 30s |
| `deployment.release.list` | `{ project_id: string, limit?: number, offset?: number }` | `ReleaseCandidateSummary[]` | 30s |
| `deployment.predeploy.run` | `{ project_id: string, release_candidate_id: string }` | `PredeployReportDTO` | **10,800s (Extended)** |
| `deployment.approval.submit` | `{ project_id: string, release_candidate_id: string, environment_id: string, action: string, decision: "approved" \| "rejected", actor_id: string, actor_role: string, comment?: string }` | `DeploymentApprovalDTO` | 30s |
| `deployment.run.execute` | `{ project_id: string, release_candidate_id: string, environment_id: string, idempotency_key?: string }` | `DeploymentRunDetail` | **10,800s (Extended)** |
| `deployment.run.get` | `{ project_id: string, deployment_run_id: string }` | `DeploymentRunDetail` | 30s |
| `deployment.health.check` | `{ project_id: string, environment_id: string, deployment_run_id?: string }` | `HealthCheckResultDTO` | 60s |
| `deployment.promote.request` | `{ project_id: string, release_candidate_id: string, from_environment_id: string, to_environment_id: string }` | `PromotionRequestDTO` | 30s |
| `deployment.promote.execute` | `{ project_id: string, promotion_request_id: string, idempotency_key?: string }` | `DeploymentRunDetail` | **10,800s (Extended)** |
| `deployment.rollback.propose` | `{ project_id: string, environment_id: string, deployment_run_id?: string }` | `DeploymentRollbackPlanDTO` | 30s |
| `deployment.rollback.execute` | `{ project_id: string, rollback_plan_id: string, idempotency_key?: string }` | `DeploymentRollbackExecutionDTO` | **10,800s (Extended)** |
| `deployment.recovery.reconcile`| `{ project_id: string }` | `DeploymentRecoveryStateDTO` | 60s |

*Note: For the 4 extended long deployment commands (`deployment.predeploy.run`, `deployment.run.execute`, `deployment.promote.execute`, `deployment.rollback.execute`), Rust manager.rs sets timeout to 10,830s to allow Python's 10,800s timeout to handle errors gracefully.*

---

## 5. Event Bus Topics

The deployment orchestrator emits real-time events over the bridge:
1. `deployment:release_created`
2. `deployment:predeploy_started` / `deployment:predeploy_completed`
3. `deployment:approval_requested` / `deployment:approval_submitted`
4. `deployment:run_started` / `deployment:run_updated` / `deployment:run_completed` / `deployment:run_failed`
5. `deployment:health_check_started` / `deployment:health_check_completed`
6. `deployment:promotion_requested` / `deployment:promotion_completed`
7. `deployment:rollback_proposed` / `deployment:rollback_started` / `deployment:rollback_completed`
8. `deployment:lease_acquired` / `deployment:lease_released` / `deployment:lease_expired`
9. `deployment:incident_created` / `deployment:incident_resolved`

*Safety Invariant*: Deployment events do not write directly to `execution_events` without valid foreign keys, preserving relational integrity.

---

## 6. Security & Governance Invariants

1. **Strict Secret Masking**: Tokens and credentials must never be written to SQLite, logs, JSON event payloads, or UI. Headers containing auth tokens must use secret references (`headers_secret_ref`).
2. **Segregation of Duties**:
   - `created_by` of `ReleaseCandidate` != `actor_id` of production `DeploymentApproval`.
   - The same actor cannot produce, review, and approve a production deployment alone.
3. **Idempotency Guarantee**: Every mutating remote call (`dispatch_workflow`, `cancel_workflow`, `execute_rollback`) requires a unique `idempotency_key`. Retries with the same key must return the existing record or fail safely.
4. **Environment Mutex**: `EnvironmentLease` is acquired atomically in SQLite. If a lease exists and has not expired, competing deployments are blocked.
5. **No Force Pushes / No Destructive Resets**: Production and remote targets are never modified via `git reset --hard` or `git push --force`.
6. **Main Branch Preservation**: The AgentMash repository `main` branch (`8db13456c61fdbe91dfdbe55819b8fec3e6989ab`) must remain strictly untouched throughout all operations.

---

## 7. Worktree Topology & File Ownership

### 7.1 Worktree Directory Structure
| Role / Agent | Path | Branch | Read/Write Permissions |
| :--- | :--- | :--- | :--- |
| **Backend Core (Codex 1)** | `../AgentMash-m5-core` | `feat/m5-backend-core` | Core backend domain, persistence, policies, state machine |
| **Backend Delivery (Codex 2)**| `../AgentMash-m5-delivery` | `feat/m5-backend-delivery` | Deployment service, adapters, health checks, bridge handlers, Rust glue |
| **Frontend (Codex 3)** | `../AgentMash-m5-frontend` | `feat/m5-frontend` | Types, API client, Zustand store, pages, components |
| **Antigravity Reviewer** | `../AgentMash-m5-review` | `detached` / read-only | **READ ONLY**: No edits, no commits, independent reviews |
| **Antigravity Lead** | `/Users/jhonatan/Downloads/AgentMesh` | `feat/v3-deployment-control` | Contract, integration, regression runner, smoke test |

### 7.2 Strict File Boundaries

#### Backend Core — Codex 1:
- `core/database/migrations/versions/0021_deployment_control_center.sql`
- `core/database/repositories/deployment_repo.py`
- `core/deployment/models.py`
- `core/deployment/state_machine.py`
- `core/deployment/policies.py`
- `core/deployment/leases.py`
- `core/deployment/telemetry.py`
- `core/deployment/recovery.py`
- `tests/python/test_deployment_core.py`
- `docs/HANDOFF_M5_CORE.md`

#### Backend Delivery — Codex 2:
- `core/deployment/service.py`
- `core/deployment/adapters/github_actions.py`
- `core/deployment/health.py`
- `core/deployment/orchestrator.py`
- `core/bridge/handlers.py` (deployment command handlers)
- `core/bridge/context.py` (wiring `deployment_service`)
- `desktop/src-tauri/src/bridge/manager.rs` (Rust timeout config)
- `tests/python/test_deployment_service.py`
- `tests/python/test_deployment_adapters.py`
- `docs/HANDOFF_M5_DELIVERY.md`

#### Frontend — Codex 3:
- `desktop/src/types/deployment.ts`
- `desktop/src/services/deploymentApi.ts`
- `desktop/src/stores/deploymentStore.ts`
- `desktop/src/pages/DeploymentCenterPage.tsx`
- `desktop/src/pages/deploymentCenter.css`
- `desktop/src/components/deployment/*`
- `desktop/src/App.tsx` (routing `/deployment` & `/deployment/:releaseId`)
- `desktop/src/pages/__tests__/DeploymentCenterPage.test.tsx`
- `desktop/src/stores/__tests__/deploymentStore.test.ts`
- `desktop/src/services/__tests__/deploymentApi.test.ts`
- `docs/agentmash-m5-deployment-ui.md`

#### Shared Files Protocol:
Any change to shared integration files (e.g. `core/bridge/context.py`, `core/orchestrator/event_sinks.py`, `desktop/src/App.tsx`) must strictly respect the contracts defined herein.

---

## 8. Review Process & Required Review Format

The **Antigravity Reviewer** must independently inspect each worktree upon handoff and before Lead integration using the following standard format:

```
REVIEW M5
Status: approved | changes_requested
Severidade: P0 | P1 | P2 | P3
Branch: <branch-name>
Commit: <commit-sha>
Arquivo: <file-path>
Evidência: <precise line or test evidence>
Impacto: <architectural, security, or reliability impact>
Correção esperada: <actionable requirement>
Responsável: <Codex 1 | Codex 2 | Codex 3 | Lead>
```

No `changes_requested` may be bypassed. Every finding must be resolved and approved before integration.

---

## 9. Handoff Protocol

When work is completed, each Codex must submit their formal handoff:

```
HANDOFF M5
Agent: <Backend Core | Backend Delivery | Frontend>
Branch: <branch-name>
Commits: <list of SHAs and titles>
Escopo: <summary of deliverables>
Arquivos: <list of changed files>
Migrations: <migration IDs if any>
Contratos utilizados: <references to section 4 and 7>
Testes executados: <exact command lines and test counts>
Resultados: <pass/fail metrics>
Riscos: <identified residual risks>
Limitações: <known limitations>
Pendências: <any pending cross-cutting items>
Recomendação para integração: <guidance for Lead>
```

---

## 10. Mandatory Real Smoke Test Specification

The smoke test must run against a **private disposable GitHub repository** (`C0mrad078/agentmash-m5-smoke-tmp` or equivalent), verifying all 20 lifecycle checkpoints:
1. DeliveryCandidate source verified merged into remote target.
2. ReleaseCandidate frozen with immutable snapshot.
3. Preflight and risk assessment passed.
4. Development deployment dispatched via GitHub Actions adapter.
5. Development verification completed and marked ready.
6. Staging promotion requested and approved by human.
7. Exact same SHA promoted to staging.
8. Health check executed against staging target.
9. Staging verification passed.
10. Production promotion requested; segregation of duties verified.
11. Reinforced human approval registered for production.
12. Exact same SHA promoted to production.
13. Controlled real failure triggered in an attempt, status persisted as failed.
14. Independent reviewer confirms incident record and suggested action.
15. Valid execution brings production to healthy state.
16. Rollback plan proposed targeting previous healthy release.
17. Human rollback approval submitted.
18. Rollback executed via provider, post-rollback health verified.
19. Crash recovery & reconciliation tested: in-flight runs reconciled, expired leases reclaimed.
20. AgentMash `main` SHA verified intact (`8db13456c61fdbe91dfdbe55819b8fec3e6989ab`).
