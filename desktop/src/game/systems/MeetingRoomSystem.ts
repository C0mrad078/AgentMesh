import { destinationPoint } from "@/game/maps/agentmashHq";
import { occupancySystem } from "@/game/systems/OccupancySystem";
import { MEETING_SEATS } from "@/game/agents/types";
import type { GridPosition } from "@/game/systems/NavigationService";

/** Spec section 39 ("Meeting Seats"): four real, reservable chairs
 * around the meeting table. */
export interface MeetingSeat {
  id: string;
  seatPoint: GridPosition;
}

const SEATS: MeetingSeat[] = MEETING_SEATS.map((id) => {
  const [x, y] = destinationPoint(id);
  return { id, seatPoint: { x, y } };
});

export class MeetingRoomSystem {
  all(): MeetingSeat[] {
    return SEATS;
  }

  claimAny(agentId: string): MeetingSeat | null {
    const spotId = occupancySystem.claimAny(SEATS.map((s) => s.id), agentId);
    return spotId ? SEATS.find((s) => s.id === spotId)! : null;
  }

  release(agentId: string): void {
    occupancySystem.release(agentId);
  }
}

export const meetingRoomSystem = new MeetingRoomSystem();
