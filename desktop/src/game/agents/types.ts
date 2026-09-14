import type { RoomId } from "@/game/maps/roomTypes";

/**
 * Stage 2 introduces a second, simulation-ready agent model, deliberately
 * separate from `office/types.ts` (which is documented to only ever hold
 * *real* backend-derived state). Everything here is driven by
 * `OfficeSimulationService` today and will be driven by real Orchestrator
 * events in Stage 3 (spec section 25/54/55) -- but never both at once,
 * and never invented from nothing.
 */

export type AgentRole = "ceo" | "designer" | "frontend_developer" | "backend_developer";

/** Every state the autonomous office understands (spec section 56). */
export type AgentState =
  | "OFFLINE"
  | "IDLE"
  | "MOVING"
  | "PLANNING"
  | "WORKING"
  | "CODING"
  | "DESIGNING"
  | "RESEARCHING"
  | "TESTING"
  | "REVIEWING"
  | "MEETING"
  | "WAITING"
  | "BLOCKED"
  | "RATE_LIMITED"
  | "COOLDOWN"
  | "RESTING"
  | "SLEEPING"
  | "ERROR"
  | "COMPLETED";

export type DestinationId =
  | RoomId
  | "lounge_sofa_01"
  | "lounge_sofa_02"
  | "coffee_machine"
  | "recovery_bed_01"
  | "recovery_bed_02"
  | "task_board"
  | "meeting_seat_01"
  | "meeting_seat_02"
  | "meeting_seat_03"
  | "meeting_seat_04"
  | "agents_entry";

export const MEETING_SEATS: DestinationId[] = [
  "meeting_seat_01", "meeting_seat_02", "meeting_seat_03", "meeting_seat_04",
];

/** Real interface prepared for future user customization (spec section
 * 5/45) -- not editable in-app yet, but every preset already goes
 * through this exact shape, and the spritesheets are generated from it
 * (`scripts/generate_office_assets.py`'s `PRESETS` dict mirrors this). */
export interface AvatarAppearance {
  skinTone: string;
  hairStyle: string;
  hairColor: string;
  shirt: string;
  pants: string;
  shoes: string;
  accessory?: string;
}

export interface AgentDefinition {
  id: string;
  name: string;
  role: AgentRole;
  roleLabel: string;
  /** Phaser texture key -- the spritesheet this preset baked (spec
   * section 46: layered runtime composition is deferred, documented in
   * GAME_ENGINE.md; each preset ships as one pre-composed sheet today). */
  textureKey: string;
  appearance: AvatarAppearance;
  homeDesk: DestinationId;
  homeRoom: RoomId;
}

/** What the simulation/state machine knows about one agent right now. */
export interface AgentRuntimeState {
  id: string;
  state: AgentState;
  destination: DestinationId | null;
  taskId: string | null;
  taskTitle: string | null;
  provider: string | null;
  progress: number | null;
  detail: string | null;
  /** Stage 3, spec section 45: set when this agent picked up the current
   * task as a real fallback from another real agent whose provider was
   * unavailable (`fallback.used`) -- the display name of that other
   * agent, or `null` when this task was assigned directly. */
  fallbackFrom: string | null;
  /** Monotonic counter of the last state change -- lets the scene tell
   * "still WORKING" apart from "just became WORKING again", without
   * needing a redundant boolean. */
  version: number;
}

export function initialRuntimeState(id: string): AgentRuntimeState {
  return {
    id, state: "IDLE", destination: null, taskId: null, taskTitle: null,
    provider: null, progress: null, detail: null, fallbackFrom: null, version: 0,
  };
}
