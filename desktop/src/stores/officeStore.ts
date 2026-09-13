import { create } from "zustand";
import { agentsApi, executionsApi, providersApi } from "@/services/api";
import { deriveOfficeSnapshot } from "@/office/stateMachine";
import type { VirtualAgent, VirtualMeeting } from "@/office/types";
import type { ExecutionStep, Task } from "@/types";

interface OfficeState {
  agents: Record<string, VirtualAgent>;
  meetings: VirtualMeeting[];
  /** The raw steps behind the derived agent states -- kept so the click
   * detail panel can show real step output/error/attempt data instead of
   * re-summarizing what's already in `VirtualAgent`. */
  steps: ExecutionStep[];
  loaded: boolean;
  error: string | null;
  refresh: (params: { activeExecutionId: string | null; activeTask: Task | null }) => Promise<void>;
}

/**
 * Re-derives the whole office snapshot from real backend state. Never
 * called on a fixed timer for step/task data -- only in response to a
 * real bridge event (see `useOfficeSync`). Provider health has no push
 * event of its own, so it is the one thing polled here, and only while
 * something is actually running (see `useOfficeSync`'s interval logic) --
 * never "every second" (spec section 12).
 */
export const useOfficeStore = create<OfficeState>((set) => ({
  agents: {},
  meetings: [],
  steps: [],
  loaded: false,
  error: null,

  refresh: async ({ activeExecutionId, activeTask }) => {
    try {
      const [agents, providerHealth, steps] = await Promise.all([
        agentsApi.list(),
        providersApi.health(),
        activeExecutionId ? executionsApi.steps(activeExecutionId) : Promise.resolve([]),
      ]);
      const snapshot = deriveOfficeSnapshot({ agents, steps, providerHealth, activeTask });
      set({ agents: snapshot.agents, meetings: snapshot.meetings, steps, loaded: true, error: null });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error), loaded: true });
    }
  },
}));
