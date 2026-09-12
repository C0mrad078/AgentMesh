import { create } from "zustand";
import { agentsApi, executionsApi, tasksApi } from "@/services/api";
import type { ExecutionProgressPayload, Task, TaskMode } from "@/types";

export interface PhaseProgress {
  phase: string;
  label: string;
  status: string;
  detail: string | null;
}

export interface AgentProgressEntry {
  agentId: string;
  agentName: string;
  status: string;
}

const TERMINAL_STEP_STATUSES = new Set(["completed", "failed", "cancelled"]);
const TERMINAL_TASK_STATUSES = new Set(["completed", "partial", "failed", "cancelled"]);

interface ExecutionState {
  activeTaskId: string | null;
  activeExecutionId: string | null;
  phases: PhaseProgress[];
  agentEntries: AgentProgressEntry[];
  costUsd: number | null;
  task: Task | null;
  submitting: boolean;
  error: string | null;

  submitTask: (input: {
    projectId: string;
    title: string;
    description?: string;
    mode?: TaskMode;
    providerInput?: Record<string, unknown>;
  }) => Promise<void>;
  handleProgressEvent: (payload: ExecutionProgressPayload) => void;
  handleOrchestrationEvent: (eventName: string, payload: { execution_id?: string }) => void;
  cancelActive: () => Promise<void>;
  reset: () => void;
  refreshTask: () => Promise<void>;
  refreshAgentProgress: () => Promise<void>;
  refreshCost: () => Promise<void>;
}

export const useExecutionStore = create<ExecutionState>((set, get) => ({
  activeTaskId: null,
  activeExecutionId: null,
  phases: [],
  agentEntries: [],
  costUsd: null,
  task: null,
  submitting: false,
  error: null,

  submitTask: async ({ projectId, title, description, mode, providerInput }) => {
    set({
      submitting: true, error: null, phases: [], agentEntries: [], costUsd: null,
      activeExecutionId: null, task: null,
    });
    try {
      const task = await tasksApi.create({
        project_id: projectId,
        title,
        description,
        mode,
        input: providerInput ?? {},
      });
      set({ activeTaskId: task.id, task });
      await executionsApi.start(task.id);
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    } finally {
      set({ submitting: false });
    }
  },

  handleProgressEvent: (payload) => {
    const { activeTaskId } = get();
    if (payload.task_id !== activeTaskId) return;

    set((state) => {
      const existingIndex = state.phases.findIndex((p) => p.phase === payload.phase);
      const entry: PhaseProgress = {
        phase: payload.phase,
        label: payload.phase_label,
        status: payload.status,
        detail: payload.detail,
      };
      const phases = [...state.phases];
      if (existingIndex >= 0) {
        phases[existingIndex] = entry;
      } else {
        phases.push(entry);
      }
      return {
        phases,
        activeExecutionId: state.activeExecutionId ?? payload.execution_id,
      };
    });

    if (payload.phase === "aggregation" && TERMINAL_STEP_STATUSES.has(payload.status)) {
      void get().refreshTask();
      void get().refreshCost();
    }
    if (payload.status === "cancelled") {
      void get().refreshTask();
    }
  },

  handleOrchestrationEvent: (eventName, payload) => {
    const { activeExecutionId } = get();
    if (!activeExecutionId || payload.execution_id !== activeExecutionId) return;

    if (["agent.selected", "step.started", "step.completed"].includes(eventName)) {
      void get().refreshAgentProgress();
    }
    if (eventName === "step.completed") {
      void get().refreshCost();
    }
  },

  cancelActive: async () => {
    const { activeExecutionId, activeTaskId } = get();
    try {
      if (activeExecutionId) {
        await executionsApi.cancel(activeExecutionId);
      } else if (activeTaskId) {
        await tasksApi.cancel(activeTaskId);
      }
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  reset: () =>
    set({
      activeTaskId: null, activeExecutionId: null, phases: [], agentEntries: [], costUsd: null,
      task: null, error: null,
    }),

  refreshTask: async () => {
    const { activeTaskId } = get();
    if (!activeTaskId) return;
    try {
      const task = await tasksApi.get(activeTaskId);
      set({ task });
      if (TERMINAL_TASK_STATUSES.has(task.status)) {
        void get().refreshAgentProgress();
      }
    } catch {
      // Best-effort refresh; the UI keeps showing the last known phase state.
    }
  },

  refreshAgentProgress: async () => {
    const { activeExecutionId } = get();
    if (!activeExecutionId) return;
    try {
      const [steps, agents] = await Promise.all([
        executionsApi.steps(activeExecutionId),
        agentsApi.list(),
      ]);
      const agentNameById = new Map(agents.map((a) => [a.id, a.name]));
      const entries: AgentProgressEntry[] = steps
        .filter((s) => s.kind === "work" && s.agent_id)
        .map((s) => ({
          agentId: s.agent_id as string,
          agentName: agentNameById.get(s.agent_id as string) ?? (s.agent_id as string),
          status: s.status,
        }));
      set({ agentEntries: entries });
    } catch {
      // best effort; the step board still reflects overall progress
    }
  },

  refreshCost: async () => {
    const { activeExecutionId } = get();
    if (!activeExecutionId) return;
    try {
      const usage = await executionsApi.usage(activeExecutionId);
      set({ costUsd: usage.total_cost_usd });
    } catch {
      // best effort
    }
  },
}));
