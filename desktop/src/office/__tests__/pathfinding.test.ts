import { describe, expect, it } from "vitest";
import { findPath } from "@/office/pathfinding";
import { destinationPoint, isWalkable } from "@/office/map";

describe("findPath", () => {
  it("returns a single-cell path when start equals goal", () => {
    const path = findPath({ x: 5, y: 5 }, { x: 5, y: 5 });
    expect(path).toEqual([{ x: 5, y: 5 }]);
  });

  it("finds a path between two open corridor cells", () => {
    const path = findPath({ x: 0, y: 0 }, { x: 20, y: 0 });
    expect(path).not.toBeNull();
    expect(path![0]).toEqual({ x: 0, y: 0 });
    expect(path![path!.length - 1]).toEqual({ x: 20, y: 0 });
  });

  it("never steps through a wall cell", () => {
    const path = findPath({ x: 0, y: 5 }, destinationPointOf("ceo_office"));
    expect(path).not.toBeNull();
    for (const cell of path!) {
      expect(isWalkable(cell.x, cell.y)).toBe(true);
    }
  });

  it("routes into a room through its door, not through its walls", () => {
    // The CEO office door is the only walkable perimeter cell -- a valid
    // path arriving at the destination must pass through it.
    const path = findPath({ x: 0, y: 15 }, destinationPointOf("ceo_office"));
    expect(path).not.toBeNull();
    const doorCell = { x: 7, y: 9 };
    expect(path!.some((c) => c.x === doorCell.x && c.y === doorCell.y)).toBe(true);
  });

  it("each step in a path is adjacent to the previous one", () => {
    const path = findPath({ x: 1, y: 1 }, destinationPointOf("testing_lab"));
    expect(path).not.toBeNull();
    for (let i = 1; i < path!.length; i++) {
      const a = path![i - 1];
      const b = path![i];
      const dist = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
      expect(dist).toBe(1);
    }
  });
});

function destinationPointOf(id: Parameters<typeof destinationPoint>[0]) {
  const [x, y] = destinationPoint(id);
  return { x, y };
}

describe("meeting seats", () => {
  it("every meeting seat is reachable through the meeting room's door", () => {
    for (const seat of ["meeting_seat_01", "meeting_seat_02", "meeting_seat_03", "meeting_seat_04"] as const) {
      const path = findPath({ x: 0, y: 0 }, destinationPointOf(seat));
      expect(path).not.toBeNull();
      expect(path!.some((c) => c.x === 22 && c.y === 9)).toBe(true); // meeting room door
    }
  });
});
