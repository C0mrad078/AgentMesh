import { destinationPoint } from "@/office/map";
import { findPath } from "@/office/pathfinding";
import type { DestinationId, GridPosition, VirtualAgent } from "@/office/types";

const STATE_COLOR_KEY: Record<VirtualAgent["state"], number> = {
  OFFLINE: 0x555555, IDLE: 0x8a8a8a, PLANNING: 0x3b82f6, MOVING: 0x8a8a8a,
  WORKING: 0x22c55e, TESTING: 0x22c55e, REVIEWING: 0x22c55e, MEETING: 0xa855f7,
  WAITING: 0xeab308, BLOCKED: 0xeab308, RATE_LIMITED: 0xf97316, RESTING: 0xf97316,
  ERROR: 0xef4444, COMPLETED: 0x22c55e,
};

/**
 * The single bridge between office state (derived in `stateMachine.ts`
 * from real backend data) and the Phaser scene. Nothing else is allowed
 * to call scene methods directly (spec section 17) -- this is what keeps
 * "dozens of React components poking Phaser" from happening.
 *
 * A minimal `SceneLike` interface (rather than importing `OfficeScene`'s
 * concrete class everywhere) keeps this testable with a plain mock, no
 * real Phaser/canvas required.
 */
export interface SceneLike {
  hasAgentSprite(agentId: string): boolean;
  ensureAgentSprite(
    agentId: string,
    name: string,
    homeCell: GridPosition,
    color: number,
    onHover: (agentId: string | null) => void,
    onClick: (agentId: string) => void,
  ): void;
  getAgentGridPosition(agentId: string): GridPosition | null;
  moveAgentAlongPath(agentId: string, path: GridPosition[]): void;
  setAgentVisual(agentId: string, state: VirtualAgent["state"]): void;
}

export class OfficeController {
  private lastDestination = new Map<string, DestinationId | null>();

  constructor(
    private readonly scene: SceneLike,
    private readonly onHover: (agentId: string | null) => void,
    private readonly onClick: (agentId: string) => void,
  ) {}

  sync(agents: Record<string, VirtualAgent>): void {
    for (const agent of Object.values(agents)) {
      if (!this.scene.hasAgentSprite(agent.id)) {
        const homeCell = this.cellFor(agent.destination ?? agent.homeRoom);
        this.scene.ensureAgentSprite(
          agent.id, agent.name, homeCell, STATE_COLOR_KEY[agent.state], this.onHover, this.onClick,
        );
        this.lastDestination.set(agent.id, agent.destination ?? agent.homeRoom);
      }

      this.scene.setAgentVisual(agent.id, agent.state);

      const target = agent.destination ?? agent.homeRoom;
      if (this.lastDestination.get(agent.id) !== target) {
        this.moveAgentTo(agent.id, target);
        this.lastDestination.set(agent.id, target);
      }
    }
  }

  private moveAgentTo(agentId: string, destination: DestinationId): void {
    const current = this.scene.getAgentGridPosition(agentId);
    if (!current) return;
    const goal = this.cellFor(destination);
    const path = findPath(current, goal);
    if (path) this.scene.moveAgentAlongPath(agentId, path);
  }

  private cellFor(destination: DestinationId): GridPosition {
    const [x, y] = destinationPoint(destination);
    return { x, y };
  }
}
