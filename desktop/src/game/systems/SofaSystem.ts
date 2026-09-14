import { destinationPoint } from "@/game/maps/agentmashHq";
import { occupancySystem } from "@/game/systems/OccupancySystem";
import type { GridPosition } from "@/game/systems/NavigationService";

/**
 * Spec section 21/38 ("Sofa System"): used for a short cooldown (below
 * `sleepThresholdMs`) -- the agent sits and rests rather than lying down.
 * Two seats, same multi-occupant pattern as `BedSystem`.
 */
export interface SofaSeat {
  id: string;
  seatPoint: GridPosition;
}

const SEAT_IDS = ["lounge_sofa_01", "lounge_sofa_02"] as const;

const SEATS: SofaSeat[] = SEAT_IDS.map((id) => {
  const [x, y] = destinationPoint(id);
  return { id, seatPoint: { x, y } };
});

export class SofaSystem {
  all(): SofaSeat[] {
    return SEATS;
  }

  claimAny(agentId: string): SofaSeat | null {
    const spotId = occupancySystem.claimAny(SEATS.map((s) => s.id), agentId);
    return spotId ? SEATS.find((s) => s.id === spotId)! : null;
  }

  release(agentId: string): void {
    occupancySystem.release(agentId);
  }
}

export const sofaSystem = new SofaSystem();
