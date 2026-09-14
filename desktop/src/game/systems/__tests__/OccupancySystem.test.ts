import { describe, expect, it, beforeEach } from "vitest";
import { OccupancySystem } from "@/game/systems/OccupancySystem";

describe("OccupancySystem", () => {
  let system: OccupancySystem;
  beforeEach(() => { system = new OccupancySystem(); });

  it("lets a free spot be claimed", () => {
    expect(system.isFree("bed_1")).toBe(true);
    expect(system.claim("bed_1", "codex")).toBe(true);
    expect(system.isFree("bed_1")).toBe(false);
  });

  it("never lets two agents claim the same spot (spec section 40)", () => {
    expect(system.claim("bed_1", "codex")).toBe(true);
    expect(system.claim("bed_1", "claude")).toBe(false);
    expect(system.occupantOfSpot("bed_1")).toBe("codex");
  });

  it("re-claiming your own spot is a no-op success, not a conflict", () => {
    expect(system.claim("bed_1", "codex")).toBe(true);
    expect(system.claim("bed_1", "codex")).toBe(true);
  });

  it("releases whatever spot an agent held when it claims a different one", () => {
    system.claim("sofa_1", "codex");
    system.claim("sofa_2", "codex");
    expect(system.isFree("sofa_1")).toBe(true);
    expect(system.occupantOfSpot("sofa_2")).toBe("codex");
  });

  it("claimAny picks the first free candidate and returns null when all are taken", () => {
    expect(system.claimAny(["bed_1", "bed_2"], "codex")).toBe("bed_1");
    expect(system.claimAny(["bed_1", "bed_2"], "claude")).toBe("bed_2");
    expect(system.claimAny(["bed_1", "bed_2"], "gemini_ceo")).toBeNull();
  });

  it("release frees the spot for someone else", () => {
    system.claim("bed_1", "codex");
    system.release("codex");
    expect(system.claim("bed_1", "claude")).toBe(true);
  });
});
