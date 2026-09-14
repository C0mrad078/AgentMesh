import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import Phaser from "phaser";
import { createOfficeGame } from "@/game/Game";
import type { AgentInspectInfo, OfficeScene, OfficeSummary } from "@/game/scenes/OfficeScene";

interface PhaserOfficeProps {
  onHoverAgent: (agentId: string | null) => void;
  onClickAgent: (agentId: string) => void;
  onTaskBoardClick: () => void;
  onSummaryChange: (summary: OfficeSummary) => void;
}

export interface PhaserOfficeHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fit: () => void;
  reset: () => void;
  followAgent: (agentId: string) => void;
  stopFollow: () => void;
  toggleDebug: () => void;
  inspect: (agentId: string) => AgentInspectInfo | null;
  listAgents: () => AgentInspectInfo[];
}

const ZOOM_STEP = 0.2;

/**
 * Mounts exactly one `Phaser.Game` (via `createOfficeGame`) for the
 * component's lifetime. Phaser's own game loop drives every agent
 * autonomously (spec section 30/37/38) -- React never re-renders this
 * component in response to office state, and never commands a
 * character's position; it only issues camera commands through `ref`
 * and receives read-only hover/click/task-board events through props.
 */
export const PhaserOffice = forwardRef<PhaserOfficeHandle, PhaserOfficeProps>(
  function PhaserOffice({ onHoverAgent, onClickAgent, onTaskBoardClick, onSummaryChange }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const onHoverRef = useRef(onHoverAgent);
    const onClickRef = useRef(onClickAgent);
    const onTaskBoardRef = useRef(onTaskBoardClick);
    const onSummaryRef = useRef(onSummaryChange);
    onHoverRef.current = onHoverAgent;
    onClickRef.current = onClickAgent;
    onTaskBoardRef.current = onTaskBoardClick;
    onSummaryRef.current = onSummaryChange;
    const sceneRef = useRef<OfficeScene | null>(null);

    useImperativeHandle(ref, () => ({
      zoomIn: () => sceneRef.current?.zoomBy(ZOOM_STEP),
      zoomOut: () => sceneRef.current?.zoomBy(-ZOOM_STEP),
      fit: () => sceneRef.current?.fitOffice(),
      reset: () => sceneRef.current?.resetCamera(),
      followAgent: (agentId: string) => sceneRef.current?.followAgent(agentId),
      stopFollow: () => sceneRef.current?.stopFollow(),
      toggleDebug: () => sceneRef.current?.toggleDebug(),
      inspect: (agentId: string) => sceneRef.current?.inspect(agentId) ?? null,
      listAgents: () => sceneRef.current?.listAgents() ?? [],
    }));

    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;

      // Real bug found via manual testing (Stage 1): React 19 StrictMode's
      // dev-only mount -> cleanup -> mount double-invoke left a *second*,
      // input-dead canvas in the DOM -- `game.destroy(true)` did not
      // reliably remove its canvas before the next mount ran. Clearing
      // the container before creating a new game guarantees exactly one
      // canvas exists no matter how Phaser's own destroy timing behaves.
      container.replaceChildren();

      const game = createOfficeGame(container);

      game.events.once(Phaser.Core.Events.READY, () => {
        game.scene.getScene("OfficeScene").events.once(Phaser.Scenes.Events.CREATE, () => {
          const scene = game.scene.getScene("OfficeScene") as unknown as OfficeScene;
          sceneRef.current = scene;

          scene.events.on("agent:hover", (agentId: string | null) => onHoverRef.current(agentId));
          scene.events.on("agent:click", (agentId: string) => onClickRef.current(agentId));
          scene.events.on("taskBoard:click", () => onTaskBoardRef.current());
          scene.events.on("agents:summary", (summary: OfficeSummary) => onSummaryRef.current(summary));
        });
      });

      const handleVisibility = () => {
        if (document.hidden) game.loop.sleep();
        else game.loop.wake();
      };
      document.addEventListener("visibilitychange", handleVisibility);

      return () => {
        document.removeEventListener("visibilitychange", handleVisibility);
        sceneRef.current = null;
        game.destroy(true);
        // Defense in depth, see the comment above the `replaceChildren()`
        // call: never trust that `destroy(true)` alone removed the canvas
        // before the next effect run.
        container.replaceChildren();
      };
    }, []);

    return <div ref={containerRef} className="h-full w-full overflow-hidden" />;
  },
);
