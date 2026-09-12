/** Mirrors `core/bridge/protocol.py` and `desktop/src-tauri/src/bridge/protocol.rs`. */

export interface BridgeErrorPayload {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export class BridgeError extends Error {
  code: string;
  details: Record<string, unknown>;

  constructor(payload: BridgeErrorPayload) {
    super(payload.message);
    this.name = "BridgeError";
    this.code = payload.code;
    this.details = payload.details;
  }
}

/** Mirrors `BridgeStatus` in `desktop/src-tauri/src/bridge/manager.rs`. */
export type BridgeConnectionStatus =
  | { status: "initializing" }
  | { status: "connected" }
  | { status: "reconnecting"; attempt: number }
  | { status: "offline" }
  | { status: "unavailable" }
  | { status: "error"; message: string };

/** Payload of an `orchestrator://event` Tauri event with `event: "execution.progress"`. */
export interface ExecutionProgressPayload {
  execution_id: string;
  task_id: string;
  phase: string;
  phase_label: string;
  status: string;
  detail: string | null;
}

export interface OrchestratorEvent {
  event: string;
  payload: ExecutionProgressPayload | Record<string, unknown>;
}
