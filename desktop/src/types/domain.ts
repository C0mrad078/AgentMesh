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
  { value: "manual", label: "Manual", available: false },
  { value: "pipeline", label: "Pipeline", available: false },
  { value: "debate", label: "Debate", available: false },
  { value: "consensus", label: "Consenso", available: false },
];
