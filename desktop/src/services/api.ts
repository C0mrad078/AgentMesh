/**
 * Typed, domain-shaped calls on top of `invokeBridge`. Command name strings
 * here must stay in sync with `core/security/allowlist.py`'s
 * `BridgeCommand` enum -- that Python enum is the single source of truth
 * for what commands exist at all.
 */

import { invokeBridge } from "@/services/bridge";
import type {
  Agent,
  BudgetLimits,
  CliProviderName,
  CliProviderStatus,
  ConnectionTestResult,
  ContextSuggestion,
  Execution,
  ExecutionEventRecord,
  ExecutionStep,
  ExecutionUsageSummary,
  LearnedRule,
  LearningCandidate,
  LearningEvent,
  LearningPolicy,
  MemoryRecordItem,
  ModelInfo,
  ModelPerformanceSummary,
  Playbook,
  PlaybookVersion,
  Project,
  PromptProposalEvent,
  PromptVersion,
  ProviderInfo,
  ProviderName,
  ReflectionRecord,
  RoutingDecisionRecord,
  Task,
  TaskMode,
  ToolCallRecord,
} from "@/types";

export const projectsApi = {
  create: (input: { name: string; description?: string; workspace_path?: string | null }) =>
    invokeBridge<Project>("project.create", input),
  get: (project_id: string) => invokeBridge<Project>("project.get", { project_id }),
  list: (include_archived = false) =>
    invokeBridge<Project[]>("project.list", { include_archived }),
  update: (
    project_id: string,
    input: Partial<Pick<Project, "name" | "description" | "workspace_path" | "status">> & {
      config?: Record<string, unknown>;
    },
  ) => invokeBridge<Project>("project.update", { project_id, ...input }),
  delete: (project_id: string) => invokeBridge<{ deleted: boolean }>("project.delete", { project_id }),
};

export const agentsApi = {
  list: () => invokeBridge<Agent[]>("agent.list"),
};

export const tasksApi = {
  create: (input: {
    project_id: string;
    title: string;
    description?: string;
    mode?: TaskMode;
    input?: Record<string, unknown>;
  }) => invokeBridge<Task>("task.create", input),
  get: (task_id: string) => invokeBridge<Task>("task.get", { task_id }),
  list: (project_id: string) => invokeBridge<Task[]>("task.list", { project_id }),
  cancel: (task_id: string) => invokeBridge<Task>("task.cancel", { task_id }),
};

export const executionsApi = {
  start: (task_id: string) =>
    invokeBridge<{ task_id: string; status: string }>("execution.start", { task_id }),
  get: (execution_id: string) => invokeBridge<Execution>("execution.get", { execution_id }),
  list: (project_id: string) => invokeBridge<Execution[]>("execution.list", { project_id }),
  cancel: (execution_id: string) =>
    invokeBridge<{ execution_id: string; cancel_requested: boolean }>("execution.cancel", {
      execution_id,
    }),
  steps: (execution_id: string) =>
    invokeBridge<ExecutionStep[]>("execution.steps.list", { execution_id }),
  events: (execution_id: string) =>
    invokeBridge<ExecutionEventRecord[]>("execution.events.list", { execution_id }),
  routing: (execution_id: string) =>
    invokeBridge<RoutingDecisionRecord[]>("execution.routing.list", { execution_id }),
  toolCalls: (execution_id: string) =>
    invokeBridge<ToolCallRecord[]>("execution.tool_calls.list", { execution_id }),
  usage: (execution_id: string) =>
    invokeBridge<ExecutionUsageSummary>("execution.usage.list", { execution_id }),
};

export const providersApi = {
  list: () => invokeBridge<ProviderInfo[]>("provider.list"),
  health: () => invokeBridge<{ provider: string; status: string; last_error: string | null; consecutive_failures: number }[]>(
    "provider.health",
  ),
  setCredential: (provider: ProviderName, api_key: string) =>
    invokeBridge<{ provider: string; enabled: boolean }>("provider.set_credential", { provider, api_key }),
  removeCredential: (provider: ProviderName) =>
    invokeBridge<{ provider: string; enabled: boolean }>("provider.remove_credential", { provider }),
  testConnection: (provider: ProviderName, api_key?: string) =>
    invokeBridge<{ provider: string; result: ConnectionTestResult }>("provider.test_connection", {
      provider,
      ...(api_key ? { api_key } : {}),
    }),
};

export const providerCliApi = {
  listStatuses: () =>
    invokeBridge<Record<CliProviderName, CliProviderStatus>>("provider.cli.status.list"),
};

export const modelsApi = {
  list: () => invokeBridge<ModelInfo[]>("model.list"),
};

export const budgetApi = {
  get: () => invokeBridge<BudgetLimits>("budget.get"),
  set: (limits: Partial<BudgetLimits>) => invokeBridge<BudgetLimits>("budget.set", limits),
};

export const settingsApi = {
  get: (key?: string) => invokeBridge<Record<string, unknown>>("settings.get", key ? { key } : {}),
  update: (key: string, value: unknown) => invokeBridge<{ key: string; value: unknown }>(
    "settings.update",
    { key, value },
  ),
};

export const healthApi = {
  check: () => invokeBridge<{ status: string }>("health.check"),
};

export const learningApi = {
  rules: (status?: string) => invokeBridge<LearnedRule[]>("learning.rules.list", status ? { status } : {}),
  pinRule: (rule_id: string) => invokeBridge<LearnedRule>("learning.rules.pin", { rule_id }),
  unpinRule: (rule_id: string) => invokeBridge<LearnedRule>("learning.rules.unpin", { rule_id }),
  rollbackRule: (rule_id: string, reason?: string) =>
    invokeBridge<LearnedRule>("learning.rules.rollback", { rule_id, reason }),
  createRule: (input: {
    title: string; category: string; rule_text: string; scope_type?: string;
    scope_value?: string | null; priority?: string;
  }) => invokeBridge<LearnedRule>("learning.rules.create", input),
  candidates: () => invokeBridge<LearningCandidate[]>("learning.candidates.list"),
  approveCandidate: (candidate_id: string) =>
    invokeBridge<LearnedRule>("learning.candidates.approve", { candidate_id }),
  rejectCandidate: (candidate_id: string, reason?: string) =>
    invokeBridge<LearningCandidate>("learning.candidates.reject", { candidate_id, reason }),
  policy: () => invokeBridge<LearningPolicy>("learning.policy.get"),
  setPolicy: (input: Partial<Omit<LearningPolicy, "id" | "updated_at">>) =>
    invokeBridge<LearningPolicy>("learning.policy.set", input),
  events: (limit = 50) => invokeBridge<LearningEvent[]>("learning.events.list", { limit }),
  export: () => invokeBridge<Record<string, unknown>>("learning.export"),
  reset: (scope: "learned_rules" | "metrics" | "playbooks" | "full") =>
    invokeBridge<{ reset: string[] }>("learning.reset", { scope, confirm: true }),
};

export const playbooksApi = {
  list: () => invokeBridge<Playbook[]>("playbook.list"),
  versions: (playbook_id: string) =>
    invokeBridge<PlaybookVersion[]>("playbook.versions.list", { playbook_id }),
};

export const modelPerformanceApi = {
  list: () => invokeBridge<ModelPerformanceSummary[]>("model_performance.list"),
};

export const contextOptimizerApi = {
  suggestions: () => invokeBridge<ContextSuggestion[]>("context_optimizer.suggestions"),
};

export const reflectionsApi = {
  forExecution: (execution_id: string) =>
    invokeBridge<ReflectionRecord[]>("reflection.list", { execution_id }),
  recent: (limit = 20) => invokeBridge<ReflectionRecord[]>("reflection.recent", { limit }),
};

export const promptsApi = {
  versions: (owner_key: string) => invokeBridge<PromptVersion[]>("prompt.versions.list", { owner_key }),
  rollback: (owner_key: string, target_version_id: string, reason?: string) =>
    invokeBridge<PromptVersion>("prompt.rollback", { owner_key, target_version_id, reason }),
  proposals: () => invokeBridge<PromptProposalEvent[]>("prompt.proposals.list"),
  applyProposal: (event_id: string) => invokeBridge<PromptVersion>("prompt.proposals.apply", { event_id }),
};

export const feedbackApi = {
  submit: (execution_id: string, rating: "up" | "down", feedback_type?: string, comment?: string) =>
    invokeBridge<{ id: string }>("execution.feedback.submit", { execution_id, rating, feedback_type, comment }),
};

export const memoryApi = {
  list: (project_id: string) => invokeBridge<MemoryRecordItem[]>("memory.list", { project_id }),
  history: (project_id: string, key: string) =>
    invokeBridge<MemoryRecordItem[]>("memory.history", { project_id, key }),
};

export interface DatabaseBackupInfo {
  path: string;
  created_at: string;
  size_bytes: number;
}

export const databaseApi = {
  createBackup: () => invokeBridge<DatabaseBackupInfo>("database.backup.create"),
  listBackups: () => invokeBridge<DatabaseBackupInfo[]>("database.backup.list"),
  restoreBackup: (path: string) =>
    invokeBridge<{ restored_from: string; restart_recommended: boolean }>("database.backup.restore", {
      path, confirm: true,
    }),
  integrityCheck: (full = false) =>
    invokeBridge<{ ok: boolean; issues: string[] }>("database.integrity_check", { full }),
};
