import { describe, expect, it } from "vitest";
import { hashString, resolveVisualProfile, VISUAL_PRESETS } from "@/game/office-domain/visualProfile";

describe("hashString", () => {
  it("is deterministic -- the same input always hashes the same way", () => {
    expect(hashString("agent_atlas")).toBe(hashString("agent_atlas"));
  });

  it("differs for different inputs (not a constant)", () => {
    expect(hashString("agent_atlas")).not.toBe(hashString("agent_forge"));
  });
});

describe("resolveVisualProfile", () => {
  it("uses the real persisted preset when it is a recognized one", () => {
    const profile = resolveVisualProfile("agent_atlas", { preset: "codex" });
    expect(profile.preset).toBe("codex");
  });

  it("falls back deterministically (never randomly) when no profile is persisted", () => {
    const first = resolveVisualProfile("agent_atlas", {});
    const second = resolveVisualProfile("agent_atlas", {});
    expect(first).toEqual(second);
    expect(VISUAL_PRESETS).toContainEqual(first);
  });

  it("falls back deterministically when the persisted preset is unrecognized", () => {
    const profile = resolveVisualProfile("agent_atlas", { preset: "not_a_real_preset" });
    expect(VISUAL_PRESETS).toContainEqual(profile);
  });

  it("the same agent id always resolves to the same fallback across calls (survives a restart)", () => {
    const resolved = Array.from({ length: 5 }, () => resolveVisualProfile("agent_forge", {}));
    expect(new Set(resolved.map((r) => r.preset)).size).toBe(1);
  });
});
