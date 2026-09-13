import { useEffect } from "react";
import { useExecutionStore } from "@/stores/executionStore";
import { useOfficeStore } from "@/stores/officeStore";

const PROVIDER_HEALTH_POLL_MS = 15_000;

/**
 * Mounted once near the app root, alongside `useBridgeSubscription`. Never
 * opens a second bridge event stream -- it reacts to `executionStore`
 * (which already turns real orchestration events into state) so the
 * office re-derives exactly when something real changed, plus a slow,
 * conditional poll for provider health (the one signal with no push event
 * of its own), only while an execution is actually active. See spec
 * section 12 "não fazer polling agressivo".
 */
export function useOfficeSync(): void {
  const refresh = useOfficeStore((s) => s.refresh);

  useEffect(() => {
    const sync = () => {
      const { activeExecutionId, task } = useExecutionStore.getState();
      void refresh({ activeExecutionId, activeTask: task });
    };

    sync(); // initial snapshot: agents idle at their desks even with nothing running

    const unsubscribeChanges = useExecutionStore.subscribe((state, prev) => {
      if (
        state.agentEntries !== prev.agentEntries ||
        state.phases !== prev.phases ||
        state.task !== prev.task ||
        state.activeExecutionId !== prev.activeExecutionId
      ) {
        sync();
      }
    });

    let interval: ReturnType<typeof setInterval> | undefined;
    const syncPollingState = () => {
      const hasActiveWork = useExecutionStore.getState().activeExecutionId !== null;
      if (hasActiveWork && !interval) {
        interval = setInterval(sync, PROVIDER_HEALTH_POLL_MS);
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
  }, [refresh]);
}
