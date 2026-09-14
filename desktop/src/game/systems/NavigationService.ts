import { isWalkable, MAP_COLS, MAP_ROWS } from "@/game/maps/agentmashHq";

export interface GridPosition {
  x: number;
  y: number;
}

interface Node {
  x: number;
  y: number;
  g: number;
  f: number;
  parent: Node | null;
}

function key(x: number, y: number): string {
  return `${x},${y}`;
}

function heuristic(ax: number, ay: number, bx: number, by: number): number {
  return Math.abs(ax - bx) + Math.abs(ay - by);
}

const NEIGHBOR_OFFSETS: [number, number][] = [
  [0, -1],
  [0, 1],
  [-1, 0],
  [1, 0],
];

/**
 * The single pathfinding authority for the game world (spec section 17/42:
 * "NavigationService"). Every walk -- the player's click-to-move, the Test
 * Agent's scripted moves, and (later) real AI agents -- routes through
 * this one A* implementation over the real collision grid derived from
 * `agentmashHq.json`. No destination is ever reached by teleporting or by
 * a precomputed/hardcoded route.
 */
export class NavigationService {
  walkable(x: number, y: number): boolean {
    return isWalkable(x, y);
  }

  get bounds(): { cols: number; rows: number } {
    return { cols: MAP_COLS, rows: MAP_ROWS };
  }

  /** Grid A* (4-directional, unit cost) from `start` to `goal`. Returns the
   * path as a list of grid cells including both endpoints, or `null` if no
   * walkable route exists. Pure and synchronous -- fully unit-testable
   * without Phaser. */
  findPath(start: GridPosition, goal: GridPosition): GridPosition[] | null {
    if (!isWalkable(goal.x, goal.y)) return null;
    if (start.x === goal.x && start.y === goal.y) return [{ ...start }];

    const open = new Map<string, Node>();
    const closed = new Set<string>();
    const startNode: Node = { x: start.x, y: start.y, g: 0, f: heuristic(start.x, start.y, goal.x, goal.y), parent: null };
    open.set(key(start.x, start.y), startNode);

    // Bounded search: a well-formed office map never needs more than a few
    // thousand expansions; this guards against a pathological/unreachable
    // case looping the whole grid without ever finding the goal.
    const maxIterations = 5000;
    let iterations = 0;

    while (open.size > 0 && iterations < maxIterations) {
      iterations += 1;
      let current: Node | null = null;
      for (const node of open.values()) {
        if (current === null || node.f < current.f) current = node;
      }
      if (current === null) break;

      if (current.x === goal.x && current.y === goal.y) {
        const path: GridPosition[] = [];
        let cursor: Node | null = current;
        while (cursor) {
          path.unshift({ x: cursor.x, y: cursor.y });
          cursor = cursor.parent;
        }
        return path;
      }

      open.delete(key(current.x, current.y));
      closed.add(key(current.x, current.y));

      for (const [dx, dy] of NEIGHBOR_OFFSETS) {
        const nx = current.x + dx;
        const ny = current.y + dy;
        const nKey = key(nx, ny);
        if (closed.has(nKey) || !isWalkable(nx, ny)) continue;

        const tentativeG = current.g + 1;
        const existing = open.get(nKey);
        if (existing && tentativeG >= existing.g) continue;

        const node: Node = {
          x: nx,
          y: ny,
          g: tentativeG,
          f: tentativeG + heuristic(nx, ny, goal.x, goal.y),
          parent: current,
        };
        open.set(nKey, node);
      }
    }

    return null;
  }
}

export const navigationService = new NavigationService();
