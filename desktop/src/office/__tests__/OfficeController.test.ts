import { describe, expect, it, vi } from "vitest";
import { OfficeController, type SceneLike } from "@/office/OfficeController";
import type { VirtualAgent } from "@/office/types";

function makeMockScene(): SceneLike & {
  sprites: Map<string, { x: number; y: number; state: VirtualAgent["state"] }>;
  moveCalls: { agentId: string; path: unknown }[];
} {
  const sprites = new Map<string, { x: number; y: number; state: VirtualAgent["state"] }>();
  const moveCalls: { agentId: string; path: unknown }[] = [];
  return {
    sprites,
    moveCalls,
    hasAgentSprite: (id) => sprites.has(id),
    ensureAgentSprite: (id, _name, homeCell) => {
      sprites.set(id, { x: homeCell.x, y: homeCell.y, state: "IDLE" });
    },
    getAgentGridPosition: (id) => {
      const s = sprites.get(id);
      return s ? { x: s.x, y: s.y } : null;
    },
    moveAgentAlongPath: (id, path) => {
      moveCalls.push({ agentId: id, path });
    },
    setAgentVisual: (id, state) => {
      const s = sprites.get(id);
      if (s) s.state = state;
    },
  };
}

function makeAgent(overrides: Partial<VirtualAgent> = {}): VirtualAgent {
  return {
    id: "agent_1", name: "Agent One", role: "Dev", provider: "openai", model: "gpt",
    homeRoom: "backend_desk", state: "IDLE", currentTaskId: null, currentStepId: null,
    currentExecutionId: null, destination: null, statusDetail: null, progress: null,
    lastActivityAt: null, retryAt: null,
    ...overrides,
  };
}

describe("OfficeController", () => {
  it("creates a sprite at the agent's home room the first time it sees it", () => {
    const scene = makeMockScene();
    const controller = new OfficeController(scene, vi.fn(), vi.fn());

    controller.sync({ agent_1: makeAgent() });

    expect(scene.hasAgentSprite("agent_1")).toBe(true);
  });

  it("moves the agent when its destination changes", () => {
    const scene = makeMockScene();
    const controller = new OfficeController(scene, vi.fn(), vi.fn());

    controller.sync({ agent_1: makeAgent({ destination: null }) });
    // A newly-created sprite spawns directly at its target cell -- no
    // walk-in-from-nowhere on first sight.
    expect(scene.moveCalls).toHaveLength(0);

    controller.sync({ agent_1: makeAgent({ destination: "meeting_room", state: "MEETING" }) });
    expect(scene.moveCalls.some((c) => c.agentId === "agent_1")).toBe(true);
  });

  it("does not re-issue a movement command when the destination has not changed", () => {
    const scene = makeMockScene();
    const controller = new OfficeController(scene, vi.fn(), vi.fn());

    controller.sync({ agent_1: makeAgent({ destination: "meeting_room" }) });
    const callsAfterFirst = scene.moveCalls.length;

    controller.sync({ agent_1: makeAgent({ destination: "meeting_room" }) });
    expect(scene.moveCalls.length).toBe(callsAfterFirst);
  });

  it("updates visual state (color/icon) even when the destination stays the same", () => {
    const scene = makeMockScene();
    const controller = new OfficeController(scene, vi.fn(), vi.fn());

    controller.sync({ agent_1: makeAgent({ state: "WORKING" }) });
    expect(scene.sprites.get("agent_1")?.state).toBe("WORKING");

    controller.sync({ agent_1: makeAgent({ state: "ERROR" }) });
    expect(scene.sprites.get("agent_1")?.state).toBe("ERROR");
  });

  it("routes hover/click callbacks through to the constructor-provided handlers", () => {
    const onHover = vi.fn();
    const onClick = vi.fn();
    let capturedHover: ((id: string) => void) | undefined;
    let capturedClick: ((id: string) => void) | undefined;

    const scene: SceneLike = {
      hasAgentSprite: () => false,
      ensureAgentSprite: (_id, _name, _cell, _color, hover, click) => {
        capturedHover = hover;
        capturedClick = click;
      },
      getAgentGridPosition: () => ({ x: 0, y: 0 }),
      moveAgentAlongPath: () => {},
      setAgentVisual: () => {},
    };

    const controller = new OfficeController(scene, onHover, onClick);
    controller.sync({ agent_1: makeAgent() });

    capturedHover?.("agent_1");
    capturedClick?.("agent_1");
    expect(onHover).toHaveBeenCalledWith("agent_1");
    expect(onClick).toHaveBeenCalledWith("agent_1");
  });
});
