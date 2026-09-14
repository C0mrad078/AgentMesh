import { describe, expect, it } from "vitest";
import { navigationService } from "@/game/systems/NavigationService";
import { AGENTS_ENTRY, destinationPoint, isWalkable } from "@/game/maps/agentmashHq";

function destTile(id: string) {
  const [x, y] = destinationPoint(id);
  return { x, y };
}

describe("NavigationService.findPath", () => {
  it("returns a single-cell path when start equals goal", () => {
    const spawn = { x: AGENTS_ENTRY[0], y: AGENTS_ENTRY[1] };
    expect(navigationService.findPath(spawn, spawn)).toEqual([spawn]);
  });

  it("finds a real route between two corridor cells", () => {
    const start = { x: AGENTS_ENTRY[0], y: AGENTS_ENTRY[1] };
    const goal = destTile("task_board");
    const path = navigationService.findPath(start, goal);
    expect(path).not.toBeNull();
    expect(path![0]).toEqual(start);
    expect(path![path!.length - 1]).toEqual(goal);
  });

  it("never steps through a blocked (wall/furniture) cell", () => {
    const start = { x: AGENTS_ENTRY[0], y: AGENTS_ENTRY[1] };
    const path = navigationService.findPath(start, destTile("ceo_office"));
    expect(path).not.toBeNull();
    for (const cell of path!) {
      expect(isWalkable(cell.x, cell.y)).toBe(true);
    }
  });

  it("routes into a room through its real door, not through its walls", () => {
    const start = { x: AGENTS_ENTRY[0], y: AGENTS_ENTRY[1] };
    const path = navigationService.findPath(start, destTile("ceo_office"));
    expect(path).not.toBeNull();
    const ceoDoor = { x: 6, y: 9 };
    expect(path!.some((c) => c.x === ceoDoor.x && c.y === ceoDoor.y)).toBe(true);
  });

  it("each step in a path is adjacent to the previous one (no teleporting)", () => {
    const start = { x: AGENTS_ENTRY[0], y: AGENTS_ENTRY[1] };
    const path = navigationService.findPath(start, destTile("testing_lab"));
    expect(path).not.toBeNull();
    for (let i = 1; i < path!.length; i++) {
      const a = path![i - 1];
      const b = path![i];
      expect(Math.abs(a.x - b.x) + Math.abs(a.y - b.y)).toBe(1);
    }
  });

  it("returns null for a goal outside the map", () => {
    const start = { x: AGENTS_ENTRY[0], y: AGENTS_ENTRY[1] };
    expect(navigationService.findPath(start, { x: -1, y: -1 })).toBeNull();
  });
});

describe("every named destination and spawn point", () => {
  const ids = [
    "ceo_office", "meeting_room", "design_desk", "frontend_desk", "backend_desk",
    "testing_lab", "lounge", "lounge_sofa_01", "lounge_sofa_02", "coffee_machine", "task_board",
    "recovery_room", "recovery_bed_01", "recovery_bed_02",
    "meeting_seat_01", "meeting_seat_02", "meeting_seat_03", "meeting_seat_04",
  ];

  it("is walkable and reachable from the agents' entry point", () => {
    const start = { x: AGENTS_ENTRY[0], y: AGENTS_ENTRY[1] };
    for (const id of ids) {
      const goal = destTile(id);
      expect(isWalkable(goal.x, goal.y)).toBe(true);
      expect(navigationService.findPath(start, goal)).not.toBeNull();
    }
  });

  it("gives every meeting seat a distinct tile", () => {
    const seats = ["meeting_seat_01", "meeting_seat_02", "meeting_seat_03", "meeting_seat_04"].map(destTile);
    const unique = new Set(seats.map((s) => `${s.x},${s.y}`));
    expect(unique.size).toBe(4);
  });
});
