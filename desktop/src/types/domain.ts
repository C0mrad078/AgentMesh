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
