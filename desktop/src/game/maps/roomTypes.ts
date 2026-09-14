/**
 * The canonical list of rooms that physically exist in the AgentMash HQ
 * tilemap. This is a fact about the map, not about the backend, so it
 * lives in `game/` and is imported both by the pure map reader
 * (`agentmashHq.ts`) and by anything -- real backend agents
 * (`office/types.ts`) or simulated ones (`game/agents/types.ts`) -- that
 * needs to name a room.
 */
export type RoomId =
  | "ceo_office"
  | "meeting_room"
  | "design_desk"
  | "frontend_desk"
  | "backend_desk"
  | "testing_lab"
  | "lounge"
  | "recovery_room";
