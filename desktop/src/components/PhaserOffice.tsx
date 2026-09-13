import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import Phaser from "phaser";
import { OfficeScene } from "@/office/scenes/OfficeScene";
import { OfficeController } from "@/office/OfficeController";
import { CELL_SIZE, GRID_COLS, GRID_ROWS } from "@/office/map";
import { useOfficeStore } from "@/stores/officeStore";

interface PhaserOfficeProps {
  onHoverAgent: (agentId: string | null) => void;
  onClickAgent: (agentId: string) => void;
  onInteractiveObjectClick: (objectId: string) => void;
}

export interface PhaserOfficeHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fit: () => void;
  reset: () => void;
  followAgent: (agentId: string) => void;
  stopFollow: () => void;
}

const ZOOM_STEP = 0.2;

/**
 * Mounts exactly one `Phaser.Game` for the component's lifetime and wires
 * it to `officeStore` through a single `OfficeController` (spec section
 * 17) -- this component itself never re-renders on office state changes;
 * it subscribes to the store imperatively so Phaser's own render loop
 * (spec section 31/32: FPS budget belongs to the models, not the canvas)
 * is the only thing driving redraws.
 *
 * Camera controls (spec section 52-55) are exposed imperatively via
 * `ref` rather than props, since they are one-shot commands ("zoom in
 * now"), not state React needs to track.
 */
export const PhaserOffice = forwardRef<PhaserOfficeHandle, PhaserOfficeProps>(
  function PhaserOffice({ onHoverAgent, onClickAgent, onInteractiveObjectClick }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    // Refs so the one-time Phaser mount below always calls the latest
    // callback without needing to re-create the game on every render.
    const onHoverRef = useRef(onHoverAgent);
    const onClickRef = useRef(onClickAgent);
    const onObjectClickRef = useRef(onInteractiveObjectClick);
    onHoverRef.current = onHoverAgent;
    onClickRef.current = onClickAgent;
    onObjectClickRef.current = onInteractiveObjectClick;
    const sceneRef = useRef<OfficeScene | null>(null);

    useImperativeHandle(ref, () => ({
      zoomIn: () => sceneRef.current?.zoomBy(ZOOM_STEP),
      zoomOut: () => sceneRef.current?.zoomBy(-ZOOM_STEP),
      fit: () => sceneRef.current?.fitOffice(),
      reset: () => sceneRef.current?.resetCamera(),
      followAgent: (agentId: string) => sceneRef.current?.followAgent(agentId),
      stopFollow: () => sceneRef.current?.stopFollow(),
    }));

    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;

      // Real bug found via manual testing: React 19 StrictMode's dev-only
      // mount -> cleanup -> mount double-invoke left a *second*,
      // input-dead canvas in the DOM -- `game.destroy(true)` did not
      // reliably remove its canvas before the next mount ran, so two
      // `<canvas>` elements stacked in the container, and every click
      // landed on the dead first one (whose Phaser instance was already
      // destroyed and had no input listeners left). Clearing the
      // container before creating a new game guarantees exactly one
      // canvas exists no matter how Phaser's own destroy timing behaves.
      container.replaceChildren();

      const game = new Phaser.Game({
        type: Phaser.AUTO,
        backgroundColor: "#14161c",
        scene: [OfficeScene],
        fps: { target: 60, min: 20 },
        render: { pixelArt: true, antialias: false },
        // Real bug found via manual testing: without an explicit Scale
        // Manager mode, the canvas renders at its fixed internal
        // resolution (1536x960) and simply overflows/gets clipped by the
        // container's `overflow-hidden` instead of fitting it -- and,
        // critically, Phaser's pointer-to-world coordinate mapping is
        // computed from the canvas's actual on-screen bounding rect, so a
        // click at the *visually* correct spot landed on the wrong grid
        // cell entirely. FIT mode keeps the fixed 1536x960 world/grid
        // coordinate system intact (nothing above this changes) while
        // letting Phaser scale the canvas via CSS *and* correctly
        // re-map pointer coordinates for that scale.
        scale: {
          mode: Phaser.Scale.FIT,
          autoCenter: Phaser.Scale.CENTER_BOTH,
          parent: container,
          width: GRID_COLS * CELL_SIZE,
          height: GRID_ROWS * CELL_SIZE,
        },
      });

      let controller: OfficeController | null = null;
      let unsubscribe: (() => void) | undefined;

      game.events.once(Phaser.Core.Events.READY, () => {
        const scene = game.scene.getScene("OfficeScene") as OfficeScene;
        sceneRef.current = scene;
        scene.events.on("interactiveObjectClicked", (objectId: string) => onObjectClickRef.current(objectId));
        controller = new OfficeController(
          scene,
          (agentId) => onHoverRef.current(agentId),
          (agentId) => onClickRef.current(agentId),
        );
        controller.sync(useOfficeStore.getState().agents);
        unsubscribe = useOfficeStore.subscribe((state, prev) => {
          if (state.agents !== prev.agents) controller?.sync(state.agents);
        });
      });

      // Pause rendering when the window loses visibility -- the orchestrator
      // keeps working, only the decorative canvas idles (spec section 31/49).
      const handleVisibility = () => {
        if (document.hidden) game.loop.sleep();
        else game.loop.wake();
      };
      document.addEventListener("visibilitychange", handleVisibility);

      return () => {
        document.removeEventListener("visibilitychange", handleVisibility);
        unsubscribe?.();
        sceneRef.current = null;
        game.destroy(true);
        // Defense in depth, see the comment above the `replaceChildren()`
        // call: never trust that `destroy(true)` alone removed the canvas
        // before the next effect run.
        container.replaceChildren();
      };
    }, []);

    return <div ref={containerRef} className="h-full w-full overflow-hidden rounded-lg" />;
  },
);
