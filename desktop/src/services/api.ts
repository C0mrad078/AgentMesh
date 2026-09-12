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
  ConnectionTestResult,
  Execution,
  ExecutionEventRecord,
  ExecutionStep,
  ExecutionUsageSummary,
  ModelInfo,
  Project,
  ProviderInfo,
  ProviderName,
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
