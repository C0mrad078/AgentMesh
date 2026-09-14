import Phaser from "phaser";
import { TILE_SIZE } from "@/game/maps/agentmashHq";
import type { GridPosition } from "@/game/systems/NavigationService";

export type Direction = "down" | "left" | "right" | "up";
const DIRECTIONS: Direction[] = ["down", "left", "right", "up"];
const FRAMES_PER_ROW = 4;

/** Depth base for every character -- always above floor/wall/furniture
 * "bottom" layers and always below the "top" foreground layers, with a
 * per-character offset from Y so characters in front of/behind each
 * other sort correctly (spec section 20). */
const CHARACTER_DEPTH_BASE = 1000;

export function characterDepth(worldY: number): number {
  return CHARACTER_DEPTH_BASE + worldY;
}

export function tileToWorld(x: number, y: number): { x: number; y: number } {
  return { x: x * TILE_SIZE + TILE_SIZE / 2, y: y * TILE_SIZE + TILE_SIZE };
}

/**
 * Registers every animation a Stage 2 agent spritesheet provides, once
 * per texture key. Row layout (see `scripts/generate_office_assets.py`):
 * 0-3 walk (down/left/right/up, idle = column 0), 4-7 seated
 * (down/left/right/up, a 4-frame subtle typing loop), 8 lying
 * (sofa rest / bed sleep, one shared pose), 9 celebrate.
 */
export function ensureCharacterAnimations(scene: Phaser.Scene, textureKey: string): void {
  if (scene.anims.exists(`${textureKey}_idle_down`)) return;
  DIRECTIONS.forEach((dir, row) => {
    const first = row * FRAMES_PER_ROW;
    scene.anims.create({
      key: `${textureKey}_idle_${dir}`,
      frames: [{ key: textureKey, frame: first }],
      frameRate: 1,
    });
    scene.anims.create({
      key: `${textureKey}_walk_${dir}`,
      frames: scene.anims.generateFrameNumbers(textureKey, { start: first, end: first + FRAMES_PER_ROW - 1 }),
      frameRate: 8,
      repeat: -1,
    });
    const seatFirst = (4 + row) * FRAMES_PER_ROW;
    scene.anims.create({
      key: `${textureKey}_seat_${dir}`,
      frames: scene.anims.generateFrameNumbers(textureKey, { start: seatFirst, end: seatFirst + FRAMES_PER_ROW - 1 }),
      frameRate: 2,
      repeat: -1,
    });
  });
  scene.anims.create({ key: `${textureKey}_lying`, frames: [{ key: textureKey, frame: 8 * FRAMES_PER_ROW }], frameRate: 1 });
  scene.anims.create({ key: `${textureKey}_celebrate`, frames: [{ key: textureKey, frame: 9 * FRAMES_PER_ROW }], frameRate: 1 });
}

/**
 * Shared movement/animation core for every autonomous agent in the world.
 * Movement always follows a real A* path at a fixed speed, tile by tile
 * -- there is no code path that sets `sprite.x`/`sprite.y` directly to a
 * destination (spec section 36/41: no teleporting).
 */
export class Character {
  readonly sprite: Phaser.GameObjects.Sprite;
  protected direction: Direction = "down";
  private path: GridPosition[] = [];
  private pathTarget: { x: number; y: number } | null = null;
  protected moving = false;
  readonly speedPxPerSec: number;

  constructor(
    protected readonly scene: Phaser.Scene,
    protected readonly textureKey: string,
    startTile: GridPosition,
    speedTilesPerSec = 4,
  ) {
    ensureCharacterAnimations(scene, textureKey);
    const { x, y } = tileToWorld(startTile.x, startTile.y);
    this.sprite = scene.add.sprite(x, y, textureKey, 0);
    this.sprite.setOrigin(0.5, 1);
    this.sprite.setDepth(characterDepth(y));
    this.speedPxPerSec = speedTilesPerSec * TILE_SIZE;
    // Deliberately NOT calling `this.playRestPose()` here: it's
    // overridden by `Agent`, whose own fields (`definition`) aren't
    // initialized until after this base constructor returns -- calling
    // the overridden version now would read them before they exist.
    // Subclasses must call `this.playRestPose()` themselves once their
    // own construction is complete.
  }

  get tilePosition(): GridPosition {
    // `tileToWorld` anchors feet at the *bottom* edge of a tile's cell
    // ((tileY+1)*TILE_SIZE), so a foot position still counts as tile Y as
    // long as it hasn't crossed past that bottom edge -- the correct
    // inverse is `ceil(feetY / TILE_SIZE) - 1`, not `floor`/`round`, or a
    // continuous walker gets misclassified by one tile near a boundary.
    return { x: Math.floor(this.sprite.x / TILE_SIZE), y: Math.ceil(this.sprite.y / TILE_SIZE) - 1 };
  }

  get isMoving(): boolean {
    return this.moving;
  }

  get currentPath(): GridPosition[] {
    return this.path;
  }

  get facing(): Direction {
    return this.direction;
  }

  /** What to play once movement stops. Overridden by `Agent` to reflect
   * the agent's current state (seated/lying/celebrating) instead of a
   * bare directional idle. */
  protected playRestPose(): void {
    this.sprite.play(`${this.textureKey}_idle_${this.direction}`, true);
  }

  private playWalk(): void {
    this.sprite.play(`${this.textureKey}_walk_${this.direction}`, true);
  }

  private faceFromDelta(dx: number, dy: number): void {
    if (Math.abs(dx) > Math.abs(dy)) {
      this.direction = dx > 0 ? "right" : "left";
    } else if (dy !== 0) {
      this.direction = dy > 0 ? "down" : "up";
    }
  }

  /** Real A* path following (spec section 17/41) -- consumes the path
   * produced by `NavigationService`, walking tile-by-tile at a fixed
   * speed. Never jumps to the destination. */
  moveAlongPath(path: GridPosition[]): void {
    const rest = path.length > 0 && path[0].x === this.tilePosition.x && path[0].y === this.tilePosition.y
      ? path.slice(1)
      : path;
    this.path = rest;
    this.pathTarget = null;
    if (this.path.length > 0) {
      this.moving = true;
      this.playWalk();
    }
  }

  stop(): void {
    this.path = [];
    this.pathTarget = null;
    this.moving = false;
    this.playRestPose();
  }

  /** Advances tweened path-following. Called every frame by the scene's
   * `update` loop -- Phaser's real game loop, not a React interval. */
  update(deltaMs: number): void {
    if (this.path.length === 0) return;

    if (!this.pathTarget) {
      const next = this.path[0];
      this.pathTarget = tileToWorld(next.x, next.y);
    }

    const target = this.pathTarget;
    const dx = target.x - this.sprite.x;
    const dy = target.y - this.sprite.y;
    const dist = Math.hypot(dx, dy);
    const step = (this.speedPxPerSec * deltaMs) / 1000;

    if (dist <= step) {
      this.sprite.x = target.x;
      this.sprite.y = target.y;
      this.sprite.setDepth(characterDepth(this.sprite.y));
      this.path.shift();
      this.pathTarget = null;
      if (this.path.length === 0) {
        this.moving = false;
        this.playRestPose();
      }
      return;
    }

    this.faceFromDelta(dx, dy);
    this.sprite.x += (dx / dist) * step;
    this.sprite.y += (dy / dist) * step;
    this.sprite.setDepth(characterDepth(this.sprite.y));
  }

  destroy(): void {
    this.sprite.destroy();
  }
}
