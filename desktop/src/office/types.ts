/**
 * Virtual Office domain types. Every field here must be derivable from
 * real backend state (agents, executions, steps, provider health) --
 * nothing in this module invents activity. See VIRTUAL_OFFICE.md.
 */

export type AgentState =
  | "OFFLINE"
  | "IDLE"
  | "PLANNING"
  | "MOVING"
  | "WORKING"
  | "TESTING"
  | "REVIEWING"
  | "MEETING"
  | "WAITING"
  | "BLOCKED"
  | "RATE_LIMITED"
  | "RESTING"
  | "ERROR"
  | "COMPLETED";

export type { RoomId } from "@/game/maps/roomTypes";
import type { RoomId } from "@/game/maps/roomTypes";

/** A named point the office graph knows how to route to -- callers ask
 * for a destination id, never raw coordinates (spec: `moveAgent(agentId,
 * "meeting_room")`, not scattered coordinates). */
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
  | "meeting_seat_04";

export const MEETING_SEATS: DestinationId[] = [
  "meeting_seat_01", "meeting_seat_02", "meeting_seat_03", "meeting_seat_04",
];

export interface GridPosition {
  x: number;
  y: number;
}

export interface VirtualAgent {
  id: string;
  name: string;
  role: string;
  provider: string;
  model: string;
  homeRoom: RoomId;
  state: AgentState;
  currentTaskId: string | null;
  currentStepId: string | null;
  currentExecutionId: string | null;
  destination: DestinationId | null;
  statusDetail: string | null;
  progress: number | null;
  lastActivityAt: string | null;
  retryAt: string | null;
}

export interface VirtualMeeting {
  id: string;
  title: string;
  participantAgentIds: string[];
  relatedStepIds: string[];
  status: "gathering" | "active" | "completed";
}

export interface OfficeSnapshot {
  agents: Record<string, VirtualAgent>;
  meetings: VirtualMeeting[];
}
