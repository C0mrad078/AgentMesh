import { useEffect } from "react";
import { useExecutionStore } from "@/stores/executionStore";
import { agentsApi, executionsApi, providersApi } from "@/services/api";
import { realOfficeAdapter } from "@/game/agents/RealOfficeAdapter";

const PROVIDER_HEALTH_POLL_MS = 15_000;

/**
 * Stage 3: the real, default source of truth for the autonomous office
 * (spec section 1 -- `OfficeSimulationService` only ever runs from
 * Developer Mode now). Mounted once near the app root, alongside
 * `useBridgeSubscription`/`useOfficeSync` -- never opens a second bridge
 * event stream. It reacts to `executionStore` (already turned real
 * `orchestrator://event` pushes into state) and re-syncs
 * `RealOfficeAdapter` -> `AgentStateMachine` exactly when something real
 * changed, plus the same slow, conditional provider-health poll
 * `useOfficeSync` uses (the one signal with no push event of its own),
 * only while an execution is actually active (spec section 40 "não
 * testar provider a cada segundo").
 */
export function useRealOfficeSync(): void {
  useEffect(() => {
    const sync = async () => {
      const { activeExecutionId, task, fallbacks } = useExecutionStore.getState();
      try {
        const [agents, providerHealth, steps] = await Promise.all([
          agentsApi.list(),
          providersApi.health(),
          activeExecutionId ? executionsApi.steps(activeExecutionId) : Promise.resolve([]),
        ]);
        realOfficeAdapter.sync({ agents, steps, providerHealth, activeTask: task }, fallbacks);
      } catch {
        // Best-effort: the office simply keeps showing its last known
        // real state until the next real event triggers a retry.
      }
    };

    void sync(); // initial snapshot on boot -- also this stage's crash-recovery reconstruction
    // (spec section 72/73): a provider already unhealthy when the app
    // starts places its agent in the Lounge/Recovery Room immediately,
    // never "magically" back at the computer.

    const unsubscribeChanges = useExecutionStore.subscribe((state, prev) => {
      if (
        state.agentEntries !== prev.agentEntries ||
        state.phases !== prev.phases ||
        state.task !== prev.task ||
        state.activeExecutionId !== prev.activeExecutionId ||
        state.fallbacks !== prev.fallbacks
      ) {
        void sync();
      }
    });

    let interval: ReturnType<typeof setInterval> | undefined;
    const syncPollingState = () => {
      const hasActiveWork = useExecutionStore.getState().activeExecutionId !== null;
      if (hasActiveWork && !interval) {
        interval = setInterval(() => void sync(), PROVIDER_HEALTH_POLL_MS);
      } else if (!hasActiveWork && interval) {
        clearInterval(interval);
        interval = undefined;
      }
    };
    syncPollingState();
    const unsubscribePolling = useExecutionStore.subscribe(syncPollingState);

    return () => {
      unsubscribeChanges();
      unsubscribePolling();
      if (interval) clearInterval(interval);
    };
  }, []);
}
