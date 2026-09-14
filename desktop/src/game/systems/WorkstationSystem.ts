import { destinationPoint } from "@/game/maps/agentmashHq";
import { occupancySystem } from "@/game/systems/OccupancySystem";
import { AGENT_DEFINITIONS } from "@/game/agents/appearancePresets";
import type { GridPosition } from "@/game/systems/NavigationService";

/**
 * Spec section 36 ("Workstation System"): every desk is `{ desk, chair,
 * computer, approach_point, seat_point }`. The tilemap already places
 * the desk/chair/computer sprites and the chair's own tile as the seat
 * point (`destinationPoint(homeDesk)`); the approach point is derived
 * geometrically (one tile further from the desk) rather than hand
 * -authored a second time in the map.
 */
export interface Workstation {
  agentId: string;
  seatPoint: GridPosition;
  approachPoint: GridPosition;
}

const WORKSTATIONS: Workstation[] = AGENT_DEFINITIONS.map((agent) => {
  const [sx, sy] = destinationPoint(agent.homeDesk);
  return { agentId: agent.id, seatPoint: { x: sx, y: sy }, approachPoint: { x: sx, y: sy + 1 } };
});

const BY_AGENT = new Map(WORKSTATIONS.map((w) => [w.agentId, w]));

export class WorkstationSystem {
  forAgent(agentId: string): Workstation | undefined {
    return BY_AGENT.get(agentId);
  }

  /** Every agent's own desk is exclusively theirs -- claiming it never
   * fails once assigned once, but still goes through `OccupancySystem`
   * so the same spot-tracking mechanism covers desks, beds, and sofas
   * uniformly. */
  claim(agentId: string): Workstation | null {
    const workstation = BY_AGENT.get(agentId);
    if (!workstation) return null;
    const spotId = `desk:${agentId}`;
    return occupancySystem.claim(spotId, agentId) ? workstation : null;
  }

  release(agentId: string): void {
    occupancySystem.release(agentId);
  }
}

export const workstationSystem = new WorkstationSystem();
