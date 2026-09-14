import React from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Real bug, found via manual testing: React 19 StrictMode's dev-only
// mount -> cleanup -> mount double-invoke left a second, input-dead
// canvas in the DOM because `Phaser.Game.destroy(true)` did not reliably
// remove its canvas before the next mount ran. This test reproduces that
// exact shape with a minimal fake `Phaser.Game` (real Phaser needs a
// canvas/WebGL context jsdom does not provide) whose `destroy()` --
// deliberately, to match the real-world failure -- does NOT remove its
// canvas, the same way the genuine bug behaved. If `PhaserOffice` did not
// defensively clear the container itself, this test would see 2 canvases.
vi.mock("phaser", () => {
  const fakeScene = { events: { on: vi.fn(), once: (_event: string, cb: () => void) => cb() } };

  class FakeGame {
    scene = { getScene: () => fakeScene };
    events = { once: (_event: string, cb: () => void) => cb() };
    loop = { sleep: vi.fn(), wake: vi.fn() };
    canvas: HTMLCanvasElement;

    constructor(config: { scale: { parent: HTMLElement } }) {
      this.canvas = document.createElement("canvas");
      config.scale.parent.appendChild(this.canvas);
    }

    destroy() {
      // Deliberately does NOT remove `this.canvas` -- reproducing the
      // real bug's behavior so the test fails without the component's
      // own defensive cleanup.
    }
  }

  class FakeScene {
    constructor(_key: string) {}
  }

  return {
    default: {
      Game: FakeGame,
      Scene: FakeScene,
      AUTO: "AUTO",
      Scale: { RESIZE: "RESIZE", FIT: "FIT", CENTER_BOTH: "CENTER_BOTH" },
      Core: { Events: { READY: "ready" } },
      Scenes: { Events: { CREATE: "create" } },
    },
  };
});

import { PhaserOffice } from "@/components/PhaserOffice";

describe("PhaserOffice", () => {
  it("never leaves more than one canvas in the DOM through a StrictMode double-mount", () => {
    const { container } = render(
      <React.StrictMode>
        <PhaserOffice
          onHoverAgent={vi.fn()}
          onClickAgent={vi.fn()}
          onTaskBoardClick={vi.fn()}
          onSummaryChange={vi.fn()}
        />
      </React.StrictMode>,
    );

    expect(container.querySelectorAll("canvas")).toHaveLength(1);
  });
});
