import Phaser from "phaser";
import { CELL_SIZE, destinationPoint, GRID_COLS, GRID_ROWS, ROOMS } from "@/office/map";
import type { AgentState, GridPosition } from "@/office/types";

const STATE_COLOR: Record<AgentState, number> = {
  OFFLINE: 0x555555,
  IDLE: 0x8a8a8a,
  PLANNING: 0x3b82f6,
  MOVING: 0x8a8a8a,
  WORKING: 0x22c55e,
  TESTING: 0x22c55e,
  REVIEWING: 0x22c55e,
  MEETING: 0xa855f7,
  WAITING: 0xeab308,
  BLOCKED: 0xeab308,
  RATE_LIMITED: 0xf97316,
  RESTING: 0xf97316,
  ERROR: 0xef4444,
  COMPLETED: 0x22c55e,
};

const STATE_ICON: Record<AgentState, string> = {
  OFFLINE: "○",
  IDLE: "·",
  PLANNING: "✎",
  MOVING: "→",
  WORKING: "⌨",
  TESTING: "✓",
  REVIEWING: "ὄ1",
  MEETING: "⬤",
  WAITING: "⏳",
  BLOCKED: "⏳",
  RATE_LIMITED: "⚠",
  RESTING: "☕",
  ERROR: "!",
  COMPLETED: "✓",
};

/** Fixed depth for every floor/wall/label -- always below every agent
 * sprite, whose depth (see `depthFor`) is derived from its Y position so
 * an agent walking "in front of" or "behind" another (or a piece of
 * furniture, once real furniture sprites exist) sorts correctly for a
 * top-down view (spec section 23). */
const ROOM_DEPTH = 0;

function depthFor(worldY: number): number {
  return 100 + worldY;
}

function toWorld(cell: GridPosition): { x: number; y: number } {
  return { x: cell.x * CELL_SIZE + CELL_SIZE / 2, y: cell.y * CELL_SIZE + CELL_SIZE / 2 };
}

interface AgentSprite {
  container: Phaser.GameObjects.Container;
  circle: Phaser.GameObjects.Arc;
  icon: Phaser.GameObjects.Text;
  label: Phaser.GameObjects.Text;
  gridPosition: GridPosition;
  activeTween: Phaser.Tweens.TweenChain | null;
}

/** Draws the office and owns every agent sprite. Never calls a bridge/API
 * itself -- all it knows is "put this sprite at this cell" / "tween it
 * along this path" / "recolor it to this state", commanded exclusively by
 * `OfficeController`. Placeholder visuals (Graphics primitives, not final
 * art) per spec section 27/28 -- swapping in real sprite sheets later is a
 * scene-only change, nothing above this layer needs to know. */
export class OfficeScene extends Phaser.Scene {
  private agentSprites = new Map<string, AgentSprite>();

  constructor() {
    super("OfficeScene");
  }

  create(): void {
    this.cameras.main.setBackgroundColor(0x14161c);
    this.drawFloorGrid();
    this.drawRooms();
    this.drawInteractiveObjects();
    this.setupCamera();
  }

  /** Static furniture-like objects (spec section 42/43) -- unlike agents,
   * these never change based on backend state, so they are created once
   * here rather than through `OfficeController`. A click emits a scene
   * event (`interactiveObjectClicked`) that `PhaserOffice` forwards to
   * real React navigation -- e.g. the Task Board opens the real Tasks
   * page, it never opens a fake in-canvas panel. */
  private drawInteractiveObjects(): void {
    const [boardX, boardY] = destinationPoint("task_board");
    const { x, y } = toWorld({ x: boardX, y: boardY - 1 });

    const board = this.add.rectangle(x, y, 26, 18, 0x1f2937);
    board.setStrokeStyle(2, 0x9ca3af);
    board.setDepth(depthFor(y));
    board.setInteractive({ useHandCursor: true });
    board.on("pointerdown", () => this.events.emit("interactiveObjectClicked", "task_board"));

    this.add
      .text(x, y - 16, "Task Board", { fontSize: "9px", color: "#9ca3af" })
      .setOrigin(0.5, 1)
      .setDepth(depthFor(y));
  }

  private drawFloorGrid(): void {
    const g = this.add.graphics();
    g.lineStyle(1, 0x22252e, 0.6);
    for (let x = 0; x <= GRID_COLS; x++) {
      g.lineBetween(x * CELL_SIZE, 0, x * CELL_SIZE, GRID_ROWS * CELL_SIZE);
    }
    for (let y = 0; y <= GRID_ROWS; y++) {
      g.lineBetween(0, y * CELL_SIZE, GRID_COLS * CELL_SIZE, y * CELL_SIZE);
    }
  }

  private drawRooms(): void {
    for (const room of ROOMS) {
      const [x1, y1, x2, y2] = room.rect;
      const px = x1 * CELL_SIZE;
      const py = y1 * CELL_SIZE;
      const width = (x2 - x1 + 1) * CELL_SIZE;
      const height = (y2 - y1 + 1) * CELL_SIZE;

      const floor = this.add.rectangle(px, py, width, height, room.color, 0.9);
      floor.setOrigin(0, 0);
      floor.setDepth(ROOM_DEPTH);

      const border = this.add.graphics();
      border.setDepth(ROOM_DEPTH);
      border.lineStyle(2, 0xffffff, 0.25);
      border.strokeRect(px, py, width, height);
      const [doorX, doorY] = room.door;
      // Visually open the door: erase a short border segment at the door cell.
      border.lineStyle(3, room.color, 1);
      if (doorY === y1 || doorY === y2) {
        border.lineBetween(doorX * CELL_SIZE, doorY === y1 ? py : py + height, (doorX + 1) * CELL_SIZE, doorY === y1 ? py : py + height);
      } else {
        border.lineBetween(doorX === x1 ? px : px + width, doorY * CELL_SIZE, doorX === x1 ? px : px + width, (doorY + 1) * CELL_SIZE);
      }

      this.add
        .text(px + 8, py + 6, room.label, { fontSize: "13px", color: "#ffffff", fontStyle: "bold" })
        .setAlpha(0.85)
        .setDepth(ROOM_DEPTH);
    }
  }

  private setupCamera(): void {
    const worldWidth = GRID_COLS * CELL_SIZE;
    const worldHeight = GRID_ROWS * CELL_SIZE;
    this.cameras.main.setBounds(0, 0, worldWidth, worldHeight);
    this.cameras.main.centerOn(worldWidth / 2, worldHeight / 2);

    this.input.on("wheel", (_pointer: unknown, _go: unknown, _dx: number, dy: number) => {
      const nextZoom = Phaser.Math.Clamp(this.cameras.main.zoom - dy * 0.001, 0.5, 2);
      this.cameras.main.setZoom(nextZoom);
    });

    let dragStart: { x: number; y: number } | null = null;
    this.input.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      if (pointer.rightButtonDown()) dragStart = { x: pointer.x, y: pointer.y };
    });
    this.input.on("pointermove", (pointer: Phaser.Input.Pointer) => {
      if (!dragStart || !pointer.rightButtonDown()) return;
      const cam = this.cameras.main;
      cam.scrollX -= (pointer.x - dragStart.x) / cam.zoom;
      cam.scrollY -= (pointer.y - dragStart.y) / cam.zoom;
      dragStart = { x: pointer.x, y: pointer.y };
    });
    this.input.on("pointerup", () => {
      dragStart = null;
    });
  }

  resetCamera(): void {
    const worldWidth = GRID_COLS * CELL_SIZE;
    const worldHeight = GRID_ROWS * CELL_SIZE;
    this.stopFollow();
    this.cameras.main.setZoom(1);
    this.cameras.main.centerOn(worldWidth / 2, worldHeight / 2);
  }

  zoomBy(delta: number): void {
    const nextZoom = Phaser.Math.Clamp(this.cameras.main.zoom + delta, 0.5, 2);
    this.cameras.main.setZoom(nextZoom);
  }

  /** "Fit office" -- zoom out just enough that the whole grid is visible
   * in the current viewport (spec section 44/52). */
  fitOffice(): void {
    this.stopFollow();
    const worldWidth = GRID_COLS * CELL_SIZE;
    const worldHeight = GRID_ROWS * CELL_SIZE;
    const cam = this.cameras.main;
    const zoom = Math.min(cam.width / worldWidth, cam.height / worldHeight);
    cam.setZoom(Phaser.Math.Clamp(zoom, 0.2, 2));
    cam.centerOn(worldWidth / 2, worldHeight / 2);
  }

  followAgent(agentId: string): boolean {
    const sprite = this.agentSprites.get(agentId);
    if (!sprite) return false;
    this.cameras.main.startFollow(sprite.container, true, 0.15, 0.15);
    return true;
  }

  stopFollow(): void {
    this.cameras.main.stopFollow();
  }

  ensureAgentSprite(
    agentId: string,
    name: string,
    homeCell: GridPosition,
    color: number,
    hoverCallback: (agentId: string | null) => void,
    clickCallback: (agentId: string) => void,
  ): void {
    if (this.agentSprites.has(agentId)) return;
    const { x, y } = toWorld(homeCell);

    const circle = this.add.circle(0, 0, 11, color);
    circle.setStrokeStyle(2, 0xffffff, 0.8);
    const icon = this.add.text(0, 0, STATE_ICON.IDLE, { fontSize: "11px", color: "#111111" }).setOrigin(0.5);
    const label = this.add
      .text(0, 18, name, { fontSize: "10px", color: "#e5e7eb" })
      .setOrigin(0.5, 0);

    const container = this.add.container(x, y, [circle, icon, label]);
    container.setSize(28, 40);
    container.setDepth(depthFor(y));
    container.setInteractive({ useHandCursor: true });
    container.on("pointerover", () => hoverCallback(agentId));
    container.on("pointerout", () => hoverCallback(null));
    container.on("pointerdown", () => clickCallback(agentId));

    this.agentSprites.set(agentId, { container, circle, icon, label, gridPosition: { ...homeCell }, activeTween: null });
  }

  setAgentVisual(agentId: string, state: AgentState): void {
    const sprite = this.agentSprites.get(agentId);
    if (!sprite) return;
    sprite.circle.setFillStyle(STATE_COLOR[state]);
    sprite.icon.setText(STATE_ICON[state]);
  }

  getAgentGridPosition(agentId: string): GridPosition | null {
    return this.agentSprites.get(agentId)?.gridPosition ?? null;
  }

  moveAgentAlongPath(agentId: string, path: GridPosition[]): void {
    const sprite = this.agentSprites.get(agentId);
    if (!sprite || path.length < 2) return;

    sprite.activeTween?.stop();
    const steps = path.slice(1);
    const chain = this.tweens.chain({
      targets: sprite.container,
      tweens: steps.map((cell) => {
        const { x, y } = toWorld(cell);
        return {
          x,
          y,
          duration: 160,
          ease: "Linear",
          onComplete: () => {
            sprite.gridPosition = cell;
            sprite.container.setDepth(depthFor(y));
          },
        };
      }),
    });
    sprite.activeTween = chain;
  }

  hasAgentSprite(agentId: string): boolean {
    return this.agentSprites.has(agentId);
  }

  agentCount(): number {
    return this.agentSprites.size;
  }
}
