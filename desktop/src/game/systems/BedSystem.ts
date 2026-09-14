import { destinationPoint } from "@/game/maps/agentmashHq";
import { occupancySystem } from "@/game/systems/OccupancySystem";
import type { GridPosition } from "@/game/systems/NavigationService";

/**
 * Spec section 22/23/37 ("Bed System"): used when a provider cooldown is
 * long enough to cross the configurable `sleepThresholdMs` (see
 * `OfficeSimulationService`) rather than a short lounge break.
 */
export interface Bed {
  id: string;
  sleepPoint: GridPosition;
  approachPoint: GridPosition;
  facingDirection: "down";
}

const BED_IDS = ["recovery_bed_01", "recovery_bed_02"] as const;

const BEDS: Bed[] = BED_IDS.map((id) => {
  const [x, y] = destinationPoint(id);
  return { id, sleepPoint: { x, y }, approachPoint: { x, y: y + 1 }, facingDirection: "down" };
});

export class BedSystem {
  all(): Bed[] {
    return BEDS;
  }

  /** Claims any free bed for `agentId`, or `null` if both are occupied --
   * a real, visible consequence of only having two beds (spec section
   * 40: no two agents share a bed). */
  claimAny(agentId: string): Bed | null {
    const spotId = occupancySystem.claimAny(BEDS.map((b) => b.id), agentId);
    return spotId ? BEDS.find((b) => b.id === spotId)! : null;
  }

  release(agentId: string): void {
    occupancySystem.release(agentId);
  }
}

export const bedSystem = new BedSystem();
