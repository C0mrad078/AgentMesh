import { ROOMS, roomAt, roomLabel, type RoomDefinition } from "@/game/maps/agentmashHq";
import type { RoomId } from "@/office/types";

/**
 * Spec section 30/31/41 ("Zonas semânticas" / "RoomRegistry"): answers
 * "which room is this tile in" and "what is this room called", sourced
 * from the map's own `Zones` object layer -- never a second, hand-typed
 * list of rectangles that could drift from the real map.
 */
export class RoomRegistry {
  all(): RoomDefinition[] {
    return ROOMS;
  }

  at(x: number, y: number): RoomId | null {
    return roomAt(x, y);
  }

  label(room: RoomId): string {
    return roomLabel(room);
  }
}

export const roomRegistry = new RoomRegistry();
