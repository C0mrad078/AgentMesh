import { describe, expect, it } from "vitest";
import { AGENTS_ENTRY, INTERACTIVE_OBJECTS, MAP_COLS, MAP_ROWS, ROOMS, roomAt, roomLabel } from "@/game/maps/agentmashHq";

describe("agentmashHq map loader", () => {
  it("parses the real map dimensions from the Tiled JSON", () => {
    expect(MAP_COLS).toBe(40);
    expect(MAP_ROWS).toBe(30);
  });

  it("parses all 8 required rooms from the Zones object layer", () => {
    const ids = ROOMS.map((r) => r.id).sort();
    expect(ids).toEqual([
      "backend_desk", "ceo_office", "design_desk", "frontend_desk", "lounge",
      "meeting_room", "recovery_room", "testing_lab",
    ]);
  });

  it("gives every room a human label", () => {
    for (const room of ROOMS) {
      expect(roomLabel(room.id)).not.toBe(room.id.toUpperCase());
      expect(roomLabel(room.id).length).toBeGreaterThan(0);
    }
  });

  it("detects which room a tile belongs to from real room rectangles", () => {
    const ceo = ROOMS.find((r) => r.id === "ceo_office")!;
    const [x1, y1] = ceo.rect;
    expect(roomAt(x1 + 1, y1 + 1)).toBe("ceo_office");
    expect(roomAt(0, 0)).toBeNull(); // outer wall shell, not inside any room
  });

  it("parses interactive objects (computers, task board) from the Objects layer", () => {
    expect(INTERACTIVE_OBJECTS.length).toBeGreaterThan(0);
    expect(INTERACTIVE_OBJECTS.some((o) => o.type === "computer")).toBe(true);
    expect(INTERACTIVE_OBJECTS.some((o) => o.type === "task_board")).toBe(true);
  });

  it("reads the agents' shared entry point from the SpawnPoints layer, not a hardcoded literal", () => {
    expect(AGENTS_ENTRY).toEqual([12, 11]);
  });
});
