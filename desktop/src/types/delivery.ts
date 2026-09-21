/** Wire DTOs: docs/agentmash-v3-milestone4-contract.md. UTC dates remain strings. */
export type DeliveryStatus = 'draft' | 'preflight_running' | 'preflight_failed' | 'awaiting_remote_approval' | 'pushing' | 'pr_open' | 'ci_running' | 'ci_failed' | 'fixing' | 'awaiting_merge_approval' | 'merging' | 'merged' | 'post_merge_failed' | 'rollback_proposed' | 'rolled_back' | 'rejected' | 'cancelled' | 'blocked';
export type DeliveryAction = 'push' | 'pr_create' | 'pr_update' | 'merge' | 'rollback';
export type MergeMethod = 'squash' | 'merge' | 'rebase';
export interface DeliveryCandidate {
  id: string; mission_id: string; project_id: string; version: number; status: DeliveryStatus;
  current_snapshot_id: string; target_remote_binding_id: string; created_at: string; updated_at: string;
}
export interface DeliverySnapshot {
  id: string; candidate_id: string; version: number; mission_id: string; project_id: string;
  base_sha: string; integration_sha: string; diff_hash: string;
  commits: { sha: string; message: string; author: string; timestamp: string }[];
  diff_stat: { files_changed: number; insertions: number; deletions: number };
  tasks_summary: { key: string; title: string; agent_id: string; status: string }[];
  reviews_summary: { reviewer_agent: string; decision: string; timestamp: string }[];
  resolved_conflicts_summary: { file_path: string; resolution_strategy: string; resolver: string }[];
  quality_gates_summary: { profile_id: string; command: string; exit_code: number; status: string }[];
  known_risks: string[]; schema_version: number; created_at: string;
}
export interface RemoteRepositoryBinding {
  id: string; project_id: string; provider: 'git' | 'github'; remote_name: string; remote_url_sanitized: string;
  owner: string | null; repository: string | null; target_branch: string; auth_detected: boolean;
  auth_type: 'ssh' | 'gh_cli' | 'token_keychain' | 'none'; permissions: string[];
  branch_protections: Record<string, unknown>; default_merge_method: MergeMethod; last_verified_at: string | null;
}
export interface PreflightReport {
  id: string; candidate_id: string; version: number; status: 'passed' | 'failed'; remote_reachable: boolean;
  base_up_to_date: boolean; clean_integration_tree: boolean; quality_gate_passed: boolean; secret_scan_passed: boolean;
  secret_findings: { file_path: string; rule_id: string; masked_sample: string; line_number: number }[];
  large_binary_findings: { file_path: string; size_bytes: number }[];
  migration_lockfile_check: { status: string; details: string };
  risk_level: 'low' | 'medium' | 'high' | 'critical'; blocking_reasons: string[]; executed_at: string;
}
export interface DeliveryApproval {
  id: string; candidate_id: string; version: number; action: DeliveryAction; decision: 'approved' | 'rejected';
  actor: string; target_sha: string; reason: string; created_at: string;
}
export interface RemoteOperation {
  id: string; candidate_id: string; operation_type: DeliveryAction; idempotency_key: string;
  payload_sanitized: Record<string, unknown>; approved_by: string; status: 'pending' | 'running' | 'completed' | 'failed';
  attempts: number; result: Record<string, unknown> | null; error_sanitized: string | null; created_at: string; updated_at: string;
}
export interface PullRequestRecord {
  id: string; candidate_id: string; remote_binding_id: string; pr_number: number | null; pr_id: string | null;
  pr_url: string | null; title: string; body: string; delivery_branch: string; target_branch: string;
  head_sha: string; base_sha: string; state: 'open' | 'closed' | 'merged'; created_at: string; updated_at: string;
}
export interface CIWorkflowRun {
  id: string; pr_record_id: string; commit_sha: string; name: string; status: 'queued' | 'in_progress' | 'completed';
  conclusion: 'success' | 'failure' | 'cancelled' | 'timed_out' | 'neutral' | 'unknown'; run_url: string | null;
  logs_sanitized: string | null; started_at: string | null; completed_at: string | null;
}
export type CICheck = CIWorkflowRun;
export interface CIFailureFinding {
  id: string; check_id: string; candidate_id: string;
  classification: 'test_failure' | 'lint_error' | 'type_error' | 'build_failure' | 'timeout' | 'infra_error';
  assigned_task_id: string | null; assigned_agent_id: string | null; worktree_path: string | null; iteration: number;
  status: 'analyzing' | 'fixing' | 'reviewed' | 'gated' | 'ready_for_push' | 'exhausted';
}
export interface PostMergeVerification {
  id: string; candidate_id: string; target_sha_observed: string;
  checks_run: { name: string; passed: boolean; detail: string }[]; status: 'passed' | 'failed'; verified_at: string;
}
export interface RollbackPlan {
  id: string; candidate_id: string; merge_commit_sha: string; strategy: 'revert_pr' | 'revert_commit';
  revert_branch: string; revert_pr_url: string | null;
  status: 'proposed' | 'awaiting_approval' | 'executing' | 'completed' | 'failed'; created_at: string;
}
export interface PhaseTelemetry {
  id: string; mission_id: string; candidate_id: string | null;
  phase: 'preflight' | 'remote_push' | 'pr_cycle' | 'ci_monitoring' | 'ci_correction' | 'merge' | 'post_merge' | 'rollback';
  started_at: string; finished_at: string | null; duration_ms: number | null;
  agent_id: string | null; session_id: string | null; provider_id: string | null; retries: number;
  token_usage: Record<string, number> | 'unknown'; cost_usd: number | 'unknown'; timeout_seconds: number | null;
  outcome: 'success' | 'failure' | 'cancelled' | 'blocked'; error_sanitized: string | null; human_touch_count: number;
}
export interface InternalStep {
  id: string; candidate_id: string; name: string; status: 'pending' | 'in_progress' | 'completed' | 'failed';
  metadata: Record<string, unknown>; created_at: string; updated_at: string;
}

export interface RemoteRepositoryBindingInput {
  project_id: string;
  provider: "git" | "github";
  remote_name?: string; // default "origin"
  remote_url: string; // sanitized on backend
  target_branch?: string; // default "main"
  default_merge_method?: "squash" | "merge" | "rebase";
}

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
  operations?: RemoteOperation[]; // alias for compatibility
  post_merge: PostMergeVerification | null;
  rollback_plan: RollbackPlan | null;
  rollback?: RollbackPlan | null; // alias for compatibility
  telemetry: PhaseTelemetry[];
  internal_steps: InternalStep[];
  recovery: DeliveryRecoveryState;
  diff_files: DiffFileEntry[];
  remote_sha: string | null;
}
