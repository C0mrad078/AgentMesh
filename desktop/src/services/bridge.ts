/**
 * Thin wrapper around the three Tauri commands Rust exposes
 * (`bridge_invoke`, `bridge_status`, `bridge_reconnect`). Every other piece
 * of frontend code that needs to talk to the core goes through
 * `src/services/api.ts`, which builds typed calls on top of `invoke()`
 * here -- nothing else in the app should import `@tauri-apps/api` directly.
 */

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { BridgeConnectionStatus, BridgeErrorPayload, OrchestratorEvent } from "@/types";
import { BridgeError } from "@/types";

export async function invokeBridge<T>(command: string, params: Record<string, unknown> = {}): Promise<T> {
  try {
    return await invoke<T>("bridge_invoke", { command, params });
  } catch (error) {
    throw toBridgeError(error);
  }
}

export async function fetchBridgeStatus(): Promise<BridgeConnectionStatus> {
  return invoke<BridgeConnectionStatus>("bridge_status");
}

export async function requestReconnect(): Promise<void> {
  await invoke<void>("bridge_reconnect");
}

export function onBridgeStatusChange(
  callback: (status: BridgeConnectionStatus) => void,
): Promise<UnlistenFn> {
  return listen<BridgeConnectionStatus>("orchestrator://status", (event) => {
    callback(event.payload);
  });
}

export function onBridgeEvent(callback: (event: OrchestratorEvent) => void): Promise<UnlistenFn> {
  return listen<OrchestratorEvent>("orchestrator://event", (event) => {
    callback(event.payload);
  });
}

function toBridgeError(error: unknown): BridgeError {
  if (isBridgeErrorPayload(error)) {
    return new BridgeError(error);
  }
  return new BridgeError({
    code: "UNKNOWN",
    message: error instanceof Error ? error.message : String(error),
    details: {},
  });
}

function isBridgeErrorPayload(value: unknown): value is BridgeErrorPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "message" in value &&
    typeof (value as { code: unknown }).code === "string"
  );
}
