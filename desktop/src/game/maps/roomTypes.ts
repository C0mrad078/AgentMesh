/**
 * The canonical list of rooms that physically exist in the AgentMash HQ
 * tilemap. This is a fact about the map, not about the backend, so it
 * lives in `game/` and is imported by anything that needs to name a room
 * (`agentmashHq.ts`'s own map reader, `RoomRegistry`, `game/agents/types.ts`).
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
