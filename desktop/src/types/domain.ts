/** Mirrors the Pydantic models in `core/projects`, `core/tasks`, `core/agents`,
 * and `core/orchestrator`. Kept as plain, hand-written interfaces (not
 * generated) since Stage 1's schema is still settling; codegen from the
 * Python side is a reasonable Stage 2+ upgrade once the schema stabilizes.
 */

export type ProjectStatus = "active" | "archived";

export interface Project {
  id: string;
  name: string;
  description: string;
  workspace_path: string | null;
  status: ProjectStatus;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type TaskStatus =
  | "queued"
  | "running"
  | "waiting"
  | "reviewing"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";

export type TaskMode = "automatic" | "manual" | "pipeline" | "debate" | "consensus";

export interface Task {
  id: string;
  project_id: string;
  conversation_id: string | null;
  title: string;
  description: string;
  mode: TaskMode;
  status: TaskStatus;
  input: Record<string, unknown>;
  result: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export type ExecutionStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface Execution {
  id: string;
  task_id: string;
  project_id: string;
  status: ExecutionStatus;
  plan: Record<string, unknown>;
  current_step_index: number;
  attempt: number;
  error: { message?: string; reasons?: string[] } | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export type StepStatus = "pending" | "running" | "completed" | "failed" | "cancelled" | "skipped";
export type StepKind = "phase" | "work";

export interface ExecutionStep {
  id: string;
  execution_id: string;
  step_index: number;
  name: string;
  kind: StepKind;
  agent_id: string | null;
  provider: string | null;
  status: StepStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  attempt: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentCapability {
  name: string;
  description: string;
}

export interface AgentPermissions {
  can_read_files: boolean;
  can_write_files: boolean;
  can_run_git: boolean;
  can_run_terminal: boolean;
  max_tokens_per_call: number | null;
}

export type ExecutionBackendType = "subscription" | "session" | "api";

/** Refactor V2, Phase 1: nothing computes this from a real session yet
 * (Presence Engine is a later phase) -- treat as the persisted default,
 * never as a live signal, until the Office actually reads it. */
export type AgentStatus = "idle" | "working" | "offline";

export interface Agent {
  id: string;
  name: string;
  description: string;
  provider: string;
  model: string;
  system_prompt: string;
  capabilities: AgentCapability[];
  tools: string[];
  permissions: AgentPermissions;
  config: Record<string, string>;
  active: boolean;
  role: string;
  avatar: string | null;
  status: AgentStatus;
  preferred_backend: ExecutionBackendType | null;
  fallback_backend: ExecutionBackendType | null;
  memory_profile: Record<string, string>;
  /** AgentMash V2, Phase 4: the primary signal the Office uses to decide
   * which project an agent belongs to. Team membership (`team_ids`,
   * below) is a secondary, orthogonal grouping. */
  project_id: string | null;
  /** Deliberately just `{preset: "<key>"}` -- see
   * `game/agents/visualProfile.ts` for the finite, real preset catalog
   * and the deterministic (never random) fallback when this is empty. */
  visual_profile: Record<string, string>;
  /** Real, computed server-side (`core.bridge.handlers._agent_to_dict`) --
   * never fabricated client-side. Empty when the agent belongs to no team. */
  team_ids: string[];
}

export interface Team {
  id: string;
  name: string;
  project_id: string | null;
  description: string;
  created_at: string;
  updated_at: string;
  /** Real, computed server-side (`core.bridge.handlers._team_list`). */
  agent_ids: string[];
}

export type SessionStatus =
  | "created" | "starting" | "working" | "waiting" | "paused"
  | "idle" | "blocked" | "completed" | "failed" | "interrupted" | "cancelled";

export const TERMINAL_SESSION_STATUSES: readonly SessionStatus[] = [
  "completed", "failed", "interrupted", "cancelled",
];

export interface Session {
  id: string;
  agent_id: string;
  project_id: string;
  provider_id: string;
  backend_type: ExecutionBackendType;
  account_id: string | null;
  task_id: string | null;
  worktree_id: string | null;
  external_session_id: string | null;
  status: SessionStatus;
  started_at: string | null;
  updated_at: string;
  finished_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export const TASK_MODES: { value: TaskMode; label: string; available: boolean }[] = [
  { value: "automatic", label: "Automático", available: true },
  { value: "manual", label: "Manual", available: true },
  { value: "pipeline", label: "Pipeline", available: true },
  { value: "debate", label: "Debate", available: true },
  { value: "consensus", label: "Consenso", available: true },
];

// --- Stage 2: providers, models, cost/usage, routing, tools ----------------

export type ProviderName = "anthropic" | "gemini" | "openai";

export type ProviderHealthStatus = "online" | "degraded" | "rate_limited" | "unavailable" | "unknown";

export type ConnectionTestResult =
  | "connected"
  | "invalid_key"
  | "timeout"
  | "rate_limited"
  | "provider_unavailable"
  | "unknown_error";

export interface ProviderInfo {
  provider: ProviderName;
  display_name: string;
  enabled: boolean;
  connected: boolean;
  health: ProviderHealthStatus;
}

export interface ProviderHealthRecord {
  provider: string;
  status: ProviderHealthStatus;
  last_error: string | null;
  consecutive_failures: number;
  /** Stage 3: real backoff duration from the adapter that raised the
   * rate limit, when it reported one -- never fabricated. */
  retry_after_seconds: number | null;
}

// --- Stage 5: CLI-wrapped providers (Codex CLI, Claude Code CLI, Gemini CLI) --

export type CliProviderName = "codex_cli" | "claude_code_cli" | "gemini_cli";

export type ProviderConnectionState = "connected" | "disconnected" | "not_installed" | "error";

export interface CliProviderStatus {
  access_method: "cli";
  state: ProviderConnectionState;
  version: string | null;
  auth_method: string | null;
  model: string | null;
  detail: string | null;
}

export interface ModelInfo {
  provider: string;
  model_id: string;
  display_name: string;
  capabilities: string[];
  context_window: number;
  supports_tools: boolean;
  supports_images: boolean;
  supports_files: boolean;
  supports_structured_output: boolean;
  input_cost_per_million_usd: number;
  output_cost_per_million_usd: number;
  priority: number;
  enabled: boolean;
}

export interface BudgetLimits {
  max_per_execution_usd: number | null;
  daily_limit_usd: number | null;
  monthly_limit_usd: number | null;
  soft_limit_ratio: number;
}

export interface UsageEntry {
  id: string;
  execution_id: string;
  step_id: string | null;
  agent_id: string | null;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  duration_seconds: number;
  success: boolean;
  retries: number;
  created_at: string;
}

export interface ExecutionUsageSummary {
  entries: UsageEntry[];
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
}

export interface RoutingDecisionRecord {
  id: string;
  execution_id: string;
  step_id: string;
  agent_id: string;
  provider: string;
  model: string;
  score: number;
  reason: string;
  alternatives: string[];
  created_at: string;
}

export interface ToolCallRecord {
  id: string;
  execution_id: string;
  step_id: string | null;
  agent_id: string | null;
  tool_name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  error: string | null;
  duration_seconds: number | null;
  created_at: string;
}

export interface ExecutionEventRecord {
  id: string;
  execution_id: string;
  task_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

// --- Stage 3: reflection, learning, playbooks, memory -----------------------

export type RuleStatus = "candidate" | "observing" | "active" | "deprecated" | "rejected" | "archived";
export type RulePriority = "critical" | "high" | "normal" | "low";
export type LearningMode = "manual" | "assisted" | "autonomous";

export interface LearnedRule {
  id: string;
  project_id: string | null;
  title: string;
  category: string;
  action: { effect?: string; agent_id?: string; magnitude?: number } | Record<string, unknown>;
  scope_type: string;
  scope_value: string | null;
  priority: RulePriority;
  status: RuleStatus;
  confidence: number;
  observations: number;
  successes: number;
  failures: number;
  distinct_projects: string[];
  pinned: boolean;
  source: string;
  last_observed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LearningCandidate {
  id: string;
  category: string;
  title: string;
  rule_text: string;
  scope_type: string;
  scope_value: string | null;
  normalized_key: string;
  observations: number;
  successes: number;
  failures: number;
  distinct_projects: string[];
  confidence: number;
  status: "candidate" | "observing" | "promoted" | "rejected";
  promoted_rule_id: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface LearningPolicy {
  id: string;
  mode: LearningMode;
  minimum_observations_for_activation: number;
  minimum_confidence: number;
  auto_apply_categories: string[];
  requires_approval_categories: string[];
  max_changes_per_day: number;
  rollback_threshold: number;
  updated_at: string;
}

export interface LearningEvent {
  id: string;
  event_type: string;
  target_type: string;
  target_id: string;
  actor: string;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface PlaybookVersion {
  id: string;
  playbook_id: string;
  version: number;
  strategy: { capability: string; step_type: string; description: string }[];
  confidence: number;
  active: boolean;
  reason: string;
  observations: number;
  successes: number;
  created_at: string;
}

export interface Playbook {
  id: string;
  task_type: string;
  name: string;
  conditions: string[];
  status: "active" | "deprecated";
  origin: string;
  created_at: string;
  updated_at: string;
}

export interface ModelPerformanceSummary {
  provider: string;
  model: string;
  agent_id: string;
  task_category: string;
  risk: string;
  executions: number;
  success_rate: number;
  verified_success_rate: number;
  failure_rate: number;
  retry_rate: number;
  avg_latency_seconds: number;
  p50_latency_seconds: number;
  p95_latency_seconds: number;
  avg_input_tokens: number;
  avg_output_tokens: number;
  avg_cost_usd: number;
  avg_iterations: number;
  review_rejection_rate: number;
}

export interface ContextSuggestion {
  task_category: string;
  samples: number;
  avg_files_included: number;
  avg_files_used: number;
  usage_ratio: number;
  suggestion: "reduce" | "expand" | "priorize";
  detail: string;
  rarely_used_extensions: string[];
}

export interface ReflectionRecord {
  id: string;
  execution_id: string;
  task_id: string | null;
  depth: "light" | "full";
  overall_score: number;
  findings: { question: string; answer: string; evidence: string }[];
  successful_patterns: string[];
  problems: string[];
  improvement_candidates: { category: string; title: string; rule_text: string }[];
  routing_feedback: string[];
  prompt_feedback: string[];
  cost_feedback: string[];
  context_feedback: string[];
  ai_narrative: string | null;
  reflection_cost_usd: number;
  created_at: string;
}

export type PromptType = "core" | "agent" | "planner" | "router" | "verifier" | "reflection" | "synthesizer";

export interface PromptVersion {
  id: string;
  owner_key: string;
  agent_id: string | null;
  prompt_type: PromptType;
  name: string;
  version: number;
  content: string;
  author: string;
  origin: string;
  reason: string;
  previous_version_id: string | null;
  protected: boolean;
  active: boolean;
  created_at: string;
}

export interface PromptProposalEvent {
  id: string;
  event_type: "prompt_proposal_generated";
  target_type: string;
  target_id: string;
  actor: string;
  evidence: {
    owner_key: string;
    prompt_type: PromptType;
    agent_id: string | null;
    current_version_id: string;
    proposed_content: string;
    reason: string;
    evidence_summary: string;
  };
  created_at: string;
}

export interface MemoryRecordItem {
  id: string;
  project_id: string;
  kind: string;
  category: string;
  key: string;
  value: Record<string, unknown>;
  importance: number;
  confidence: number;
  provenance: { source_execution_id: string | null; source_file: string | null; source_user_input: boolean };
  valid_from: string | null;
  valid_until: string | null;
  superseded_by: string | null;
  created_at: string;
  updated_at: string;
}
