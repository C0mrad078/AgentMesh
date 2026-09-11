import { create } from "zustand";
import { executionsApi, tasksApi } from "@/services/api";
import type { ExecutionProgressPayload, Task, TaskMode } from "@/types";

export interface PhaseProgress {
  phase: string;
  label: string;
  status: string;
  detail: string | null;
}

const TERMINAL_STEP_STATUSES = new Set(["completed", "failed", "cancelled"]);

interface ExecutionState {
  activeTaskId: string | null;
  activeExecutionId: string | null;
  phases: PhaseProgress[];
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
  cancelActive: () => Promise<void>;
  reset: () => void;
  refreshTask: () => Promise<void>;
}

export const useExecutionStore = create<ExecutionState>((set, get) => ({
  activeTaskId: null,
  activeExecutionId: null,
  phases: [],
  task: null,
  submitting: false,
  error: null,

  submitTask: async ({ projectId, title, description, mode, providerInput }) => {
    set({ submitting: true, error: null, phases: [], activeExecutionId: null, task: null });
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
    }
    if (payload.status === "cancelled") {
      void get().refreshTask();
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

  reset: () => set({ activeTaskId: null, activeExecutionId: null, phases: [], task: null, error: null }),

  refreshTask: async () => {
    const { activeTaskId } = get();
    if (!activeTaskId) return;
    try {
      const task = await tasksApi.get(activeTaskId);
      set({ task });
    } catch {
      // Best-effort refresh; the UI keeps showing the last known phase state.
    }
  },
}));
