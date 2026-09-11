import { create } from "zustand";
import { fetchBridgeStatus, onBridgeStatusChange, requestReconnect } from "@/services/bridge";
import type { BridgeConnectionStatus } from "@/types";

interface ConnectionState {
  status: BridgeConnectionStatus;
  initialized: boolean;
  init: () => Promise<void>;
  reconnect: () => Promise<void>;
}

export const useConnectionStore = create<ConnectionState>((set, get) => ({
  status: { status: "initializing" },
  initialized: false,

  init: async () => {
    if (get().initialized) return;
    set({ initialized: true });

    await onBridgeStatusChange((status) => set({ status }));

    try {
      const status = await fetchBridgeStatus();
      set({ status });
    } catch {
      // The status listener above will still receive updates once the
      // sidecar reports in; a transient failure to read the initial value
      // is not fatal.
    }
  },

  reconnect: async () => {
    await requestReconnect();
  },
}));
