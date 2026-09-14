import Phaser from "phaser";
import { AGENTS_ENTRY, INTERACTIVE_OBJECTS, isWalkable, MAP_COLS, MAP_ROWS, TILE_SIZE } from "@/game/maps/agentmashHq";
import { TILE_COMPUTER } from "@/game/maps/tileIds";
import { Agent } from "@/game/entities/Agent";
import { CameraController } from "@/game/systems/CameraController";
import { roomRegistry } from "@/game/systems/RoomRegistry";
import { buildAgentDefinition } from "@/game/agents/appearancePresets";
import { agentStateMachine } from "@/game/agents/AgentStateMachine";
import { officeRosterStore, type OfficeRoster } from "@/game/agents/officeRosterStore";
import type { AgentDefinition, AgentRuntimeState } from "@/game/agents/types";
import type { GridPosition } from "@/game/systems/NavigationService";

const WORLD_WIDTH = MAP_COLS * TILE_SIZE;
const WORLD_HEIGHT = MAP_ROWS * TILE_SIZE;

function tileCenterWorld(x: number, y: number): { x: number; y: number } {
  return { x: x * TILE_SIZE + TILE_SIZE / 2, y: y * TILE_SIZE + TILE_SIZE / 2 };
}

export interface OfficeSummary {
  working: number;
  meeting: number;
  resting: number;
  sleeping: number;
  waiting: number;
  error: number;
  idle: number;
}

const WORKING_STATES = new Set(["PLANNING", "WORKING", "CODING", "DESIGNING", "RESEARCHING", "TESTING", "REVIEWING"]);
const WAITING_STATES = new Set(["WAITING", "BLOCKED"]);

function summarize(runtimes: AgentRuntimeState[]): OfficeSummary {
  const summary: OfficeSummary = { working: 0, meeting: 0, resting: 0, sleeping: 0, waiting: 0, error: 0, idle: 0 };
  for (const r of runtimes) {
    if (WORKING_STATES.has(r.state)) summary.working += 1;
    else if (r.state === "MEETING") summary.meeting += 1;
    else if (r.state === "RESTING") summary.resting += 1;
    else if (r.state === "SLEEPING") summary.sleeping += 1;
    else if (WAITING_STATES.has(r.state)) summary.waiting += 1;
    else if (r.state === "ERROR") summary.error += 1;
    else summary.idle += 1;
  }
  return summary;
}

export interface AgentInspectInfo {
  id: string;
  name: string;
  roleLabel: string;
  state: string;
  taskTitle: string | null;
  provider: string | null;
  progress: number | null;
  detail: string | null;
  room: string | null;
  /** Stage 3, spec section 45: the real agent's name this task was
   * picked up from, when a real `fallback.used` event moved it here
   * because the other agent's provider was unavailable. */
  fallbackFrom: string | null;
}

/**
 * The autonomous 2D office (Stage 2 -- see GAME_ENGINE.md). Renders the
 * real `agentmashHq.json` tilemap; every character it shows and every
 * movement they make is a direct consequence of real domain state --
 * there is no user-controlled character and no click-to-move (spec
 * section 30). The user only ever commands the camera and, in Developer
 * Mode, the `OfficeSimulationService` debug controls exposed by
 * `OfficePage`.
 *
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md): the roster is no
 * longer a fixed 4-entry array baked in at `create()` time -- it starts
 * empty and reacts to `officeRosterStore` (written by
 * `OfficeDomainAdapter`, itself fed by real, persisted `Agent`/`Team`/
 * `Session` rows), spawning/updating/despawning real `Agent` game objects
 * as the real roster changes. This scene never imports anything from
 * `@/services`, `@/stores`, or `@/types` -- it only ever reacts to
 * already-computed state (spec "NÃO ACOPLAR PHASER AO BACKEND").
 */
export class OfficeScene extends Phaser.Scene {
  private agents = new Map<string, Agent>();
  private definitions = new Map<string, AgentDefinition>();
  private camera!: CameraController;
  private debugGraphics!: Phaser.GameObjects.Graphics;
  private debugText!: Phaser.GameObjects.Text;
  private debugEnabled = false;
  private unsubscribeStateMachine: (() => void) | null = null;
  private unsubscribeRoster: (() => void) | null = null;
  private hoveredAgentId: string | null = null;

  constructor() {
    super("OfficeScene");
  }

  create(): void {
    this.cameras.main.setBackgroundColor(0x0c0d11);

    const map = this.make.tilemap({ key: "office" });
    const tileset = map.addTilesetImage("agentmash_tileset", "tileset")!;

    const ground = map.createLayer("Ground", tileset, 0, 0)!;
    const floor = map.createLayer("Floor", tileset, 0, 0)!;
    const floorDetails = map.createLayer("FloorDetails", tileset, 0, 0)!;
    const wallsBottom = map.createLayer("WallsBottom", tileset, 0, 0)!;
    const furnitureBottom = map.createLayer("FurnitureBottom", tileset, 0, 0)!;
    const furnitureTop = map.createLayer("FurnitureTop", tileset, 0, 0)!;
    const wallsTop = map.createLayer("WallsTop", tileset, 0, 0)!;

    [ground, floor, floorDetails].forEach((l, i) => l.setDepth(i));
    wallsBottom.setDepth(3);
    furnitureBottom.setDepth(4);
    furnitureTop.setDepth(2000);
    wallsTop.setDepth(2001);

    this.drawInteractiveObjectSprites();

    this.unsubscribeStateMachine = agentStateMachine.onChange((agentId, runtime) => {
      this.agents.get(agentId)?.applyRuntimeState(runtime);
      this.events.emit("agents:summary", summarize(agentStateMachine.all()));
    });

    // Real roster reconstruction (crash/reload recovery, spec section
    // 72/73's spirit applied to the domain layer): apply whatever
    // `OfficeDomainAdapter` already knows immediately, then react to
    // every future change -- never wait for a fresh push before showing
    // agents that were already real when this scene was created.
    this.applyRoster(officeRosterStore.get());
    this.unsubscribeRoster = officeRosterStore.subscribe((roster) => this.applyRoster(roster));

    this.camera = new CameraController(this, WORLD_WIDTH, WORLD_HEIGHT);
    this.camera.fit();

    this.debugGraphics = this.add.graphics().setDepth(3000).setVisible(false);
    this.debugText = this.add.text(8, 0, "", {
      fontSize: "10px", color: "#8ff08f", fontFamily: "monospace",
      backgroundColor: "#000000cc", padding: { x: 4, y: 3 },
    })
      .setScrollFactor(0)
      .setDepth(3001)
      .setVisible(false);
    this.positionDebugText();

    this.input.keyboard!.addKey(Phaser.Input.Keyboard.KeyCodes.BACKTICK).on("down", () => this.toggleDebug());

    this.scale.on("resize", (size: Phaser.Structs.Size) => {
      this.cameras.main.setSize(size.width, size.height);
      this.positionDebugText();
    });

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.unsubscribeStateMachine?.();
      this.unsubscribeRoster?.();
    });
  }

  /** The one place real agents become (or stop being) Phaser game
   * objects -- spawns a new `Agent` for a roster id never seen before,
   * despawns one no longer present, and respawns one whose visual
   * identity changed (a name/preset edited in Team while the Office was
   * open). Never touches ids the roster didn't mention. */
  private applyRoster(roster: OfficeRoster): void {
    const nextIds = new Set(roster.models.map((m) => m.agentId));

    for (const [agentId, agent] of this.agents) {
      if (!nextIds.has(agentId)) {
        agent.destroy();
        this.agents.delete(agentId);
        this.definitions.delete(agentId);
      }
    }

    for (const model of roster.models) {
      const def = buildAgentDefinition(model, roster.showProjectLabels);
      const previous = this.definitions.get(model.agentId);
      const identityChanged = previous && (previous.textureKey !== def.textureKey || previous.name !== def.name);

      if (!previous || identityChanged) {
        this.agents.get(model.agentId)?.destroy();
        const spawnTile = this.agents.get(model.agentId)?.tilePosition
          ?? { x: AGENTS_ENTRY[0], y: AGENTS_ENTRY[1] };
        const agent = new Agent(this, def, spawnTile);
        agent.sprite.setInteractive({ useHandCursor: true });
        agent.sprite.on("pointerover", () => {
          this.hoveredAgentId = model.agentId;
          this.events.emit("agent:hover", model.agentId);
        });
        agent.sprite.on("pointerout", () => {
          if (this.hoveredAgentId === model.agentId) this.hoveredAgentId = null;
          this.events.emit("agent:hover", null);
        });
        agent.sprite.on("pointerdown", () => this.events.emit("agent:click", model.agentId));
        this.agents.set(model.agentId, agent);
      }
      this.definitions.set(model.agentId, def);
    }

    this.events.emit("agents:summary", summarize(agentStateMachine.all()));
  }

  private positionDebugText(): void {
    // Clears both the (HTML, always-on-top) Developer Mode panel and the
    // debug/dev toolbar buttons, which also live in the bottom-left.
    this.debugText.setY(this.cameras.main.height - 200);
  }

  update(_time: number, delta: number): void {
    for (const agent of this.agents.values()) agent.update(delta);
    if (this.debugEnabled) this.renderDebugOverlay();
  }

  private drawInteractiveObjectSprites(): void {
    for (const obj of INTERACTIVE_OBJECTS) {
      const { x, y } = tileCenterWorld(obj.tile[0], obj.tile[1]);
      if (obj.type === "computer") {
        // Decorative only -- agents "use" it by sitting at the adjacent
        // chair (spec section 36); there is no player to walk up and
        // interact with it anymore.
        this.add.image(x, y - 6, "tileset", TILE_COMPUTER).setDepth(5);
      } else if (obj.type === "task_board") {
        const board = this.add.rectangle(x, y - 8, 26, 18, 0x1f2937).setStrokeStyle(2, 0x9ca3af).setDepth(5);
        this.add.text(x, y - 24, "Task Board", { fontSize: "9px", color: "#9ca3af" }).setOrigin(0.5, 1).setDepth(5);
        board.setInteractive({ useHandCursor: true });
        board.on("pointerdown", () => this.events.emit("taskBoard:click"));
      }
    }
  }

  private renderDebugOverlay(): void {
    const g = this.debugGraphics;
    g.clear();

    g.fillStyle(0xff0033, 0.28);
    const cam = this.cameras.main;
    const x0 = Math.max(0, Math.floor(cam.worldView.x / TILE_SIZE));
    const y0 = Math.max(0, Math.floor(cam.worldView.y / TILE_SIZE));
    const x1 = Math.min(MAP_COLS, Math.ceil((cam.worldView.x + cam.worldView.width) / TILE_SIZE));
    const y1 = Math.min(MAP_ROWS, Math.ceil((cam.worldView.y + cam.worldView.height) / TILE_SIZE));
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        if (!isWalkable(x, y)) g.fillRect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE);
      }
    }

    g.lineStyle(2, 0x38bdf8, 0.8);
    for (const room of roomRegistry.all()) {
      const [rx1, ry1, rx2, ry2] = room.rect;
      g.strokeRect(rx1 * TILE_SIZE, ry1 * TILE_SIZE, (rx2 - rx1 + 1) * TILE_SIZE, (ry2 - ry1 + 1) * TILE_SIZE);
    }

    g.lineStyle(2, 0x60a5fa, 0.9);
    for (const agent of this.agents.values()) {
      if (agent.currentPath.length <= 1) continue;
      const pts = agent.currentPath.map((c) => tileCenterWorld(c.x, c.y));
      g.beginPath();
      g.moveTo(pts[0].x, pts[0].y);
      for (const p of pts.slice(1)) g.lineTo(p.x, p.y);
      g.strokePath();
    }

    const lines = [`FPS: ${this.game.loop.actualFps.toFixed(0)}`, `Agents: ${this.agents.size}`];
    for (const [agentId, def] of this.definitions) {
      const agent = this.agents.get(agentId)!;
      const runtime = agentStateMachine.get(agentId);
      const room = roomRegistry.at(agent.tilePosition.x, agent.tilePosition.y);
      const status = agent.isMoving ? "MOVING" : (runtime?.state ?? "?");
      lines.push(`${def.name}: ${status} @ ${room ?? "corridor"} (${agent.tilePosition.x},${agent.tilePosition.y})`);
    }
    this.debugText.setText(lines.join("\n"));
  }

  // ---------------------------------------------------------------------
  // Camera controls exposed to `PhaserOffice.tsx` via its imperative ref
  // (spec section 31/33: the user only ever controls the camera).
  // ---------------------------------------------------------------------

  zoomBy(delta: number): void {
    this.camera.zoomBy(delta);
  }

  fitOffice(): void {
    this.camera.fit();
  }

  resetCamera(): void {
    this.camera.reset();
  }

  followAgent(agentId: string): boolean {
    const agent = this.agents.get(agentId);
    if (!agent) return false;
    this.camera.follow(agent.sprite);
    return true;
  }

  stopFollow(): void {
    this.camera.stopFollow();
  }

  toggleDebug(): void {
    this.debugEnabled = !this.debugEnabled;
    this.debugGraphics.setVisible(this.debugEnabled);
    this.debugText.setVisible(this.debugEnabled);
  }

  /** Spec section 32: clicking (or hovering) an agent never controls it
   * -- it only surfaces read-only inspection data for the UI. */
  inspect(agentId: string): AgentInspectInfo | null {
    const def = this.definitions.get(agentId);
    const agent = this.agents.get(agentId);
    const runtime = agentStateMachine.get(agentId);
    if (!def || !agent || !runtime) return null;
    const room = roomRegistry.at(agent.tilePosition.x, agent.tilePosition.y);
    return {
      id: agentId,
      name: def.name,
      roleLabel: def.roleLabel,
      state: agent.isMoving ? "MOVING" : runtime.state,
      taskTitle: runtime.taskTitle,
      provider: runtime.provider,
      progress: runtime.progress,
      detail: runtime.detail,
      room: room ? roomRegistry.label(room) : null,
      fallbackFrom: runtime.fallbackFrom,
    };
  }

  listAgents(): AgentInspectInfo[] {
    return [...this.definitions.keys()].map((id) => this.inspect(id)!).filter(Boolean);
  }
}

// Re-exported for callers that only need the grid-position shape.
export type { GridPosition };
