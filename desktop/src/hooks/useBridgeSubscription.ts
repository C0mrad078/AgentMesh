import { useEffect } from "react";
import { onBridgeEvent } from "@/services/bridge";
import { useConnectionStore } from "@/stores/connectionStore";
import { useExecutionStore } from "@/stores/executionStore";
import type { ExecutionProgressPayload } from "@/types";

/**
 * Mounted once near the app root. Wires the two Tauri event streams
 * (`orchestrator://status`, `orchestrator://event`) into the zustand stores
 * so the rest of the component tree only ever reads store state, never
 * touches `@tauri-apps/api` directly.
 */
export function useBridgeSubscription(): void {
  const initConnection = useConnectionStore((s) => s.init);
  const handleProgressEvent = useExecutionStore((s) => s.handleProgressEvent);
  const handleOrchestrationEvent = useExecutionStore((s) => s.handleOrchestrationEvent);

  useEffect(() => {
    void initConnection();

    let unlisten: (() => void) | undefined;
    void onBridgeEvent((event) => {
      if (event.event === "execution.progress") {
        handleProgressEvent(event.payload as ExecutionProgressPayload);
      } else {
        handleOrchestrationEvent(event.event, event.payload as { execution_id?: string });
      }
    }).then((fn) => {
      unlisten = fn;
    });

    return () => unlisten?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
