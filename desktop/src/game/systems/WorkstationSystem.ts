import { destinationPoint } from "@/game/maps/agentmashHq";
import { occupancySystem } from "@/game/systems/OccupancySystem";
import type { GridPosition } from "@/game/systems/NavigationService";

/**
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md "DESK ASSIGNMENT" /
 * "OVERFLOW"): the map physically has four authored desk positions
 * (`ceo_office`, `design_desk`, `frontend_desk`, `backend_desk` -- real
 * named points in `agentmashHq.json`, unchanged this phase). Stage 2/3
 * bound each one permanently to one of exactly 4 fixed character ids;
 * now that any number of real agents can be assigned to a project, this
 * is a real, anonymous *pool* instead -- claimed by whichever real
 * agent id asks first, exactly like `SofaSystem`/`BedSystem`/
 * `MeetingRoomSystem` already do for their own pooled resources (this
 * was the one outlier still doing fixed 1:1 binding).
 *
 * `WORKSTATION_CAPACITY` (4) is the current, honest, documented limit: a
 * 5th+ simultaneously-active agent in one project does not crash or
 * silently overwrite another's desk -- `AgentStateMachine` sends it to
 * the lounge (an overflow gathering area) instead, exactly the "overflow
 * zone" the brief asks for. Growing capacity later means adding more
 * named desk points to the map, not changing this system's shape.
 */
export interface Workstation {
  deskId: string;
  seatPoint: GridPosition;
  approachPoint: GridPosition;
}

const DESK_IDS = ["ceo_office", "design_desk", "frontend_desk", "backend_desk"] as const;

const DESKS: Workstation[] = DESK_IDS.map((deskId) => {
  const [sx, sy] = destinationPoint(deskId);
  return { deskId, seatPoint: { x: sx, y: sy }, approachPoint: { x: sx, y: sy + 1 } };
});

export const WORKSTATION_CAPACITY = DESKS.length;

export class WorkstationSystem {
  all(): Workstation[] {
    return DESKS;
  }

  /** Claims whichever desk this agent already holds, or the first free
   * one in the pool. `null` means every desk is taken (overflow) --
   * never a crash, never a silently-shared desk. */
  claim(agentId: string): Workstation | null {
    const deskId = occupancySystem.claimAny(DESKS.map((d) => d.deskId), agentId);
    return deskId ? DESKS.find((d) => d.deskId === deskId)! : null;
  }

  release(agentId: string): void {
    occupancySystem.release(agentId);
  }
}

export const workstationSystem = new WorkstationSystem();
