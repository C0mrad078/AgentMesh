import { useConnectionStore } from "@/stores/connectionStore";
import type { BridgeConnectionStatus } from "@/types";

export type ConnectionTone = "neutral" | "success" | "warning" | "destructive";

export interface ConnectionDisplay {
  label: string;
  tone: ConnectionTone;
  isConnected: boolean;
  canRetry: boolean;
}

export function describeConnectionStatus(status: BridgeConnectionStatus): ConnectionDisplay {
  switch (status.status) {
    case "initializing":
      return { label: "Inicializando", tone: "neutral", isConnected: false, canRetry: false };
    case "connected":
      return { label: "Conectado", tone: "success", isConnected: true, canRetry: false };
    case "reconnecting":
      return {
        label: `Reconectando (tentativa ${status.attempt})`,
        tone: "warning",
        isConnected: false,
        canRetry: false,
      };
    case "offline":
      return { label: "Offline", tone: "destructive", isConnected: false, canRetry: true };
    case "error":
      return { label: `Erro: ${status.message}`, tone: "destructive", isConnected: false, canRetry: true };
  }
}

export function useConnectionStatus(): ConnectionDisplay & { status: BridgeConnectionStatus } {
  const status = useConnectionStore((s) => s.status);
  return { ...describeConnectionStatus(status), status };
}
