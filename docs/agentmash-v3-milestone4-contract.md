# AgentMash V3 — Milestone 4 Shared Contract: Delivery Control Center

This document establishes the binding architectural contract, domain models, state machine, bridge protocol, file ownership boundaries, and verification criteria for **Milestone 4 (Controlled Delivery)**.

---

## 1. Architectural Mission & Objectives

The purpose of Milestone 4 is to govern the transition of an approved `integration` branch into a reviewable, validated, and controlled remote delivery, without allowing unvetted or direct modifications to `main`.

### Key Guarantees:
1. **Frozen Immutability**: Once an integration branch is approved, a `DeliveryCandidate` and immutable `DeliverySnapshot` freeze base SHA, integration SHA, diff hash, commits, tasks, agents, and gates. Any subsequent modification or correction creates a new candidate version.
2. **Preflight Gate**: Remote actions require a clean tree, up-to-date base ancestry, security secret scan, size checks, quality gate pass, and risk classification.
3. **Explicit Human Approvals**: Distinct human approvals are mandatory for (a) remote branch push, (b) PR creation/updates, (c) merge execution, and (d) rollback execution. Head SHA changes automatically invalidate previous merge approvals.
4. **Idempotency**: All mutating remote operations use deterministic idempotency keys. Retries never duplicate branches, PRs, or merge commits.
5. **CI Loop & Bounded Agent Corrections**: CI status checks are observed; failures spawn structured correction tasks in fresh worktrees with independent agent review and re-gating. Cycles are bounded (default max 3).
6. **Controlled Merge & Rollback via Revert**: Merge is performed via pull request respecting repository branch protections. Rollback is executed via `git revert` or revert PR; destructive resets are strictly prohibited.
7. **Phase Telemetry**: Accurate, per-phase timing, retry count, agent/session metrics, and human touch points are persisted. Unknown fields remain `unknown` (never fabricated zero).

---

## 2. Domain Models & Entities

### 2.1 Delivery Candidate & Snapshot
- **`DeliveryCandidate`**:
  - `id`: string (UUID)
  - `mission_id`: string
  - `project_id`: string
  - `version`: int (starts at 1, increments on correction cycles)
  - `status`: `DeliveryStatus`
  - `current_snapshot_id`: string
  - `target_remote_binding_id`: string
  - `created_at`: datetime (UTC)
  - `updated_at`: datetime (UTC)

- **`DeliverySnapshot`**:
  - `id`: string
  - `candidate_id`: string
  - `version`: int
  - `mission_id`: string
  - `project_id`: string
  - `base_sha`: string (SHA-1)
  - `integration_sha`: string (SHA-1)
  - `diff_hash`: string (SHA-256 of normalized diff)
  - `commits`: list of `{ sha, message, author, timestamp }`
  - `diff_stat`: `{ files_changed: int, insertions: int, deletions: int }`
  - `tasks_summary`: list of `{ key, title, agent_id, status }`
  - `reviews_summary`: list of `{ reviewer_agent, decision, timestamp }`
  - `resolved_conflicts_summary`: list of `{ file_path, resolution_strategy, resolver }`
  - `quality_gates_summary`: list of `{ profile_id, command, exit_code, status }`
  - `known_risks`: list of string
  - `schema_version`: int (1)
  - `created_at`: datetime (UTC)

### 2.2 Remote Repository Binding
- **`RemoteRepositoryBinding`**:
  - `id`: string
  - `project_id`: string
  - `provider`: `Literal["git", "github"]`
  - `remote_name`: string (default `"origin"`)
  - `remote_url_sanitized`: string (e.g. `https://github.com/owner/repo.git` without embedded credentials)
  - `owner`: string | None
  - `repository`: string | None
  - `target_branch`: string (default `"main"`)
  - `auth_detected`: bool
  - `auth_type`: `Literal["ssh", "gh_cli", "token_keychain", "none"]`
  - `permissions`: list of string (e.g. `["pull", "push", "admin"]`)
  - `branch_protections`: dict (e.g. `requires_pr`, `required_status_checks`, `strict`)
  - `default_merge_method`: `Literal["squash", "merge", "rebase"]`
  - `last_verified_at`: datetime | None

### 2.3 Preflight Report
- **`PreflightReport`**:
  - `id`: string
  - `candidate_id`: string
  - `version`: int
  - `status`: `Literal["passed", "failed"]`
  - `remote_reachable`: bool
  - `base_up_to_date`: bool
  - `clean_integration_tree`: bool
  - `quality_gate_passed`: bool
  - `secret_scan_passed`: bool
  - `secret_findings`: list of `{ file_path, rule_id, masked_sample, line_number }`
  - `large_binary_findings`: list of `{ file_path, size_bytes }`
  - `migration_lockfile_check`: `{ status: str, details: str }`
  - `risk_level`: `Literal["low", "medium", "high", "critical"]`
  - `blocking_reasons`: list of string
  - `executed_at`: datetime

### 2.4 Delivery Approvals & Remote Operations
- **`DeliveryApproval`**:
  - `id`: string
  - `candidate_id`: string
  - `version`: int
  - `action`: `Literal["push", "pr_create", "pr_update", "merge", "rollback"]`
  - `decision`: `Literal["approved", "rejected"]`
  - `actor`: string (human user / session identifier)
  - `target_sha`: string (approved commit SHA)
  - `reason`: string
  - `created_at`: datetime

- **`RemoteOperation`**:
  - `id`: string
  - `candidate_id`: string
  - `operation_type`: `Literal["push", "pr_create", "pr_update", "merge", "rollback"]`
  - `idempotency_key`: string (UUID or deterministic hash)
  - `payload_sanitized`: dict[str, Any]
  - `approved_by`: string
  - `status`: `Literal["pending", "running", "completed", "failed"]`
  - `attempts`: int
  - `result`: dict[str, Any] | None
  - `error_sanitized`: str | None
  - `created_at`: datetime
  - `updated_at`: datetime

### 2.5 Pull Request & CI Records
- **`PullRequestRecord`**:
  - `id`: string
  - `candidate_id`: string
  - `remote_binding_id`: string
  - `pr_number`: int | None
  - `pr_id`: string | None
  - `pr_url`: string | None
  - `title`: string
  - `body`: string
  - `delivery_branch`: string
  - `target_branch`: string
  - `head_sha`: string
  - `base_sha`: string
  - `state`: `Literal["open", "closed", "merged"]`
  - `created_at`: datetime
  - `updated_at`: datetime

- **`CIWorkflowRun` & `CICheck`**:
  - `id`: string
  - `pr_record_id`: string
  - `commit_sha`: string
  - `name`: string
  - `status`: `Literal["queued", "in_progress", "completed"]`
  - `conclusion`: `Literal["success", "failure", "cancelled", "timed_out", "neutral", "unknown"]`
  - `run_url`: string | None
  - `logs_sanitized`: string | None
  - `started_at`: datetime | None
  - `completed_at`: datetime | None

- **`CIFailureFinding`**:
  - `id`: string
  - `check_id`: string
  - `candidate_id`: string
  - `classification`: `Literal["test_failure", "lint_error", "type_error", "build_failure", "timeout", "infra_error"]`
  - `assigned_task_id`: string | None
  - `assigned_agent_id`: string | None
  - `worktree_path`: string | None
  - `iteration`: int
  - `status`: `Literal["analyzing", "fixing", "reviewed", "gated", "ready_for_push", "exhausted"]`

### 2.6 Post Merge & Rollback
- **`PostMergeVerification`**:
  - `id`: string
  - `candidate_id`: string
  - `target_sha_observed`: string
  - `checks_run`: list of `{ name: str, passed: bool, detail: str }`
  - `status`: `Literal["passed", "failed"]`
  - `verified_at`: datetime

- **`RollbackPlan`**:
  - `id`: string
  - `candidate_id`: string
  - `merge_commit_sha`: string
  - `strategy`: `Literal["revert_pr", "revert_commit"]`
  - `revert_branch`: string
  - `revert_pr_url`: string | None
  - `status`: `Literal["proposed", "awaiting_approval", "executing", "completed", "failed"]`
  - `created_at`: datetime

### 2.7 Phase Telemetry & Internal Step
- **`PhaseTelemetry`**:
  - `id`: string
  - `mission_id`: string
  - `candidate_id`: string | None
  - `phase`: `Literal["preflight", "remote_push", "pr_cycle", "ci_monitoring", "ci_correction", "merge", "post_merge", "rollback"]`
  - `started_at`: datetime
  - `finished_at`: datetime | None
  - `duration_ms`: int | None
  - `agent_id`: string | None
  - `session_id`: string | None
  - `provider_id`: string | None
  - `retries`: int
  - `token_usage`: dict[str, int] | Literal["unknown"]
  - `cost_usd`: float | Literal["unknown"]
  - `timeout_seconds`: int | None
  - `outcome`: `Literal["success", "failure", "cancelled", "blocked"]`
  - `error_sanitized`: str | None
  - `human_touch_count`: int

- **`InternalStep`**:
  - `id`: string
  - `candidate_id`: string
  - `name`: string
  - `status`: `Literal["pending", "in_progress", "completed", "failed"]`
  - `metadata`: dict[str, Any]
  - `created_at`: datetime
  - `updated_at`: datetime

---

## 3. State Machine & Transitions

```
[draft]
   │
   ▼ (delivery.preflight.run)
[preflight_running] ──(fail)──► [preflight_failed]
   │ (pass)                           │ (retry)
   ▼                                  └───────┘
[awaiting_remote_approval]
   │ (approve push)
   ▼ (delivery.remote.push)
[pushing] ──(success)──► [pr_open]
                            │
                            ▼ (CI polling)
                    [ci_running]
                     │        │
            (all pass)│        │ (check failed)
                     │        ▼
                     │   [ci_failed]
                     │        │ (assign fix & worktree)
                     │        ▼
                     │    [fixing] ──(iter > limit)──► [blocked / human_input_required]
                     │        │ (correction pass & new version)
                     │        └───────► [pushing] (new candidate version)
                     ▼
         [awaiting_merge_approval]
                     │ (approve merge; invalidated if HEAD changes)
                     ▼ (delivery.merge.execute)
                 [merging]
                     │
                     ▼
                  [merged] ──(verification fail)──► [post_merge_failed]
                     │                                     │
                     ▼ (optional rollback)                 ▼
             [rollback_proposed] ──────────────────────────┘
                     │ (approve revert)
                     ▼ (delivery.rollback.execute)
                [rolled_back]

Terminal rejection states at any approval gate: [rejected], [cancelled], [blocked].
```

---

## 4. Bridge Commands & DTOs

All commands are registered in `core.security.allowlist.BridgeCommand` and mapped to typed handlers.

| Bridge Command | Input Parameters | Output Response | Description |
|---|---|---|---|
| `delivery.candidate.create` | `{ mission_id: str, project_id: str }` | `DeliveryCandidateDetail` | Creates frozen candidate & snapshot from approved integration branch. |
| `delivery.candidate.get` | `{ candidate_id: str }` | `DeliveryCandidateDetail` | Returns full state, snapshot, preflight, PR, CI runs, telemetry. |
| `delivery.candidate.list` | `{ project_id?: str, mission_id?: str }` | `list[DeliveryCandidateSummary]` | Lists delivery candidates. |
| `delivery.preflight.run` | `{ candidate_id: str }` | `PreflightReport` | Runs preflight checks (remote, clean tree, secrets, gates). |
| `delivery.binding.get` | `{ project_id: str }` | `RemoteRepositoryBinding` | Gets configured remote repository binding for project. |
| `delivery.binding.save` | `RemoteRepositoryBindingInput` | `RemoteRepositoryBinding` | Creates or updates remote binding (sanitizes URL). |
| `delivery.approval.submit` | `{ candidate_id: str, action: str, decision: "approved" \| "rejected", reason?: str, actor: str }` | `DeliveryApproval` | Submits human decision for push, PR, merge, or rollback. |
| `delivery.remote.push` | `{ candidate_id: str, idempotency_key: str }` | `RemoteOperation` | Pushes delivery branch remotely (requires prior push approval). |
| `delivery.pr.create` | `{ candidate_id: str, idempotency_key: str }` | `PullRequestRecord` | Creates PR with summary, tasks, tests, risks. |
| `delivery.pr.update` | `{ candidate_id: str, idempotency_key: str }` | `PullRequestRecord` | Updates PR after correction cycle. |
| `delivery.ci.status` | `{ candidate_id: str }` | `list[CIWorkflowRun]` | Fetches latest status checks/workflow runs. |
| `delivery.ci.assign_fix`| `{ candidate_id: str, finding_id: str, agent_id?: str }` | `CIFailureFinding` | Spawns a correction worktree & task for CI failure. |
| `delivery.merge.execute`| `{ candidate_id: str, idempotency_key: str, merge_method?: str }` | `RemoteOperation` | Merges PR (requires merge approval & matching head SHA). |
| `delivery.rollback.propose`| `{ candidate_id: str, reason: str }` | `RollbackPlan` | Prepares revert branch / revert PR plan. |
| `delivery.rollback.execute`| `{ candidate_id: str, idempotency_key: str }` | `RemoteOperation` | Executes revert without destructive resets. |
| `delivery.telemetry.list` | `{ candidate_id?: str, mission_id?: str }` | `list[PhaseTelemetry]` | Returns phase timing and telemetry data. |

### Tauri / Desktop Bridge Events
- Event: `"orchestrator://event"`
- Payloads:
  - `{ event: "delivery.candidate_updated", payload: { candidate_id, status, version } }`
  - `{ event: "delivery.preflight_progress", payload: { candidate_id, step, status } }`
  - `{ event: "delivery.ci_updated", payload: { candidate_id, pr_number, checks_summary } }`
  - `{ event: "delivery.operation_progress", payload: { candidate_id, operation_id, status } }`

### 4.1 Concrete Bridge DTO Specifications

#### `RemoteRepositoryBindingInput`
```typescript
export interface RemoteRepositoryBindingInput {
  project_id: string;
  provider: "git" | "github";
  remote_name?: string; // default "origin"
  remote_url: string; // sanitized on backend
  owner?: string | null;
  repository?: string | null;
  target_branch?: string; // default "main"
  default_merge_method?: "squash" | "merge" | "rebase";
}
```

#### `DeliveryCandidateSummary`
```typescript
export interface DeliveryCandidateSummary {
  id: string;
  mission_id: string;
  project_id: string;
  version: number;
  status: DeliveryStatus;
  base_sha: string;
  integration_sha: string;
  remote_sha: string | null;
  pr_number: number | null;
  pr_url: string | null;
  risk_level: "low" | "medium" | "high" | "critical";
  has_pending_approvals: boolean;
  created_at: string;
  updated_at: string;
}
```

#### `DeliveryCandidateDetail`
```typescript
export interface DiffFileEntry {
  path: string;
  status: "added" | "modified" | "deleted";
  additions: number;
  deletions: number;
}

export interface DeliveryRecoveryState {
  is_blocked: boolean;
  recovery_reason: string | null;
  suggested_action: "retry_preflight" | "request_approval" | "assign_ci_fix" | "revert_merge" | "human_intervention" | null;
}

export interface DeliveryCandidateDetail {
  candidate: DeliveryCandidate;
  snapshot: DeliverySnapshot;
  remote_binding: RemoteRepositoryBinding | null;
  preflight: PreflightReport | null;
  pull_request: PullRequestRecord | null;
  ci_runs: CIWorkflowRun[];
  ci_findings: CIFailureFinding[];
  approvals: DeliveryApproval[];
  pending_approvals: Array<"push" | "pr_create" | "pr_update" | "merge" | "rollback">;
  remote_operations: RemoteOperation[];
  post_merge: PostMergeVerification | null;
  rollback: RollbackPlan | null;
  telemetry: PhaseTelemetry[];
  recovery: DeliveryRecoveryState;
  diff_files: DiffFileEntry[];
  remote_sha: string | null;
}
```

---

## 5. File Ownership Matrix

Strict boundary separation between workers:

### Codex 1 — Backend / Delivery Engine
- **Primary Directories & Modules**:
  - `core/delivery/` (models, state machine, service, preflight, git_remote, github_adapter, ci_monitor, telemetry, recovery)
  - `core/database/migrations/versions/0020_delivery_control_center.sql`
  - `core/database/repositories/delivery_repo.py`
  - `core/security/allowlist.py` (add `DELIVERY_*` commands to `BridgeCommand`)
  - `core/bridge/handlers.py` (implement delivery handlers dispatching to `delivery_service`)
  - `tests/python/test_delivery_*.py`
- **Restrictions**:
  - Do NOT touch React UI components (`desktop/src/components/`, `desktop/src/pages/`, etc.).
  - Do NOT commit tokens or mock tokens in plain text.
  - Do NOT perform unapproved remote pushes or destructive resets during tests.

### Codex 2 — Delivery Center / UI
- **Primary Directories & Modules**:
  - `desktop/src/types/delivery.ts` (TypeScript types mirroring backend models and DTOs)
  - `desktop/src/services/deliveryApi.ts` (API client calling `invokeBridge`)
  - `desktop/src/pages/DeliveryCenterPage.tsx`
  - `desktop/src/components/delivery/` (CandidateOverview, PreflightCard, RemoteBindingCard, PullRequestCard, CiStatusCard, FailureFixCard, ApprovalModal, RollbackCard, TelemetryCard)
  - `desktop/src/stores/deliveryStore.ts` (Zustand store for delivery state & events)
  - `desktop/src/pages/AgentWorkspacePage.tsx` (navigation link / delivery badge)
  - `desktop/src/App.tsx` (Route for `/delivery/:candidateId` and `/delivery`)
  - `desktop/src/pages/__tests__/DeliveryCenterPage.test.tsx` and component unit tests
- **Restrictions**:
  - Do NOT modify Python code, migrations, or database repositories.
  - Do NOT invent fake domain rules or fake state transitions on the client; use the bridge commands.
  - If a bridge command or DTO needs adjustment, request it from Codex 1 and Lead via Maestri.

### Antigravity — Lead Architect, Integrator & QA
- Establish shared contract (`docs/agentmash-v3-milestone4-contract.md`).
- Create and provision worktrees (`../AgentMash-m4-backend`, `../AgentMash-m4-ui`).
- Coordinate execution and resolve contract questions on Maestri.
- Conduct independent diff reviews of Codex 1 and Codex 2 handoffs.
- Integrate both branches into `feat/v3-delivery-control` and review any glue code.
- Run complete test suites (Python, Vitest, Rust).
- Execute mandatory disposable remote smoke test on a private disposable repository (never touch AgentMash main).
- Compile final acceptance report.

---

## 6. Testing & Acceptance Criteria

### Automated Test Requirements:
1. **Migrations**: clean setup from 0001 to 0020 and upgrade test.
2. **Snapshot Immutability**: assertions that snapshot cannot be updated in-place after creation; version bumps on modification.
3. **Preflight**: tests verifying failure when tree is dirty, base is behind target, or credentials leak in diff.
4. **Idempotency**: duplicate remote calls with same idempotency key return existing record without secondary side-effects.
5. **Approval Enforcement**: pushing or merging without approval raises validation error; head changes invalidate prior merge approvals.
6. **CI Failure Loop**: verification of finding generation, task assignment, worktree creation, and bounded retry limit.
7. **Telemetry**: validation that missing metrics default to `"unknown"` instead of zero.
8. **UI Verification**: Delivery Center rendering all states (loading, empty, preflight failed, PR open, CI running, awaiting approval, merged, rollback).
9. **Zero Regression**: Marcos 1-3 test suite remains green; Pixel Office unaffected.
10. **Repository Hygiene**: AgentMash `main` remains untouched at SHA `8db13456c61fdbe91dfdbe55819b8fec3e6989ab`.
