import Phaser from "phaser";
import { BootScene } from "@/game/scenes/BootScene";
import { OfficeScene } from "@/game/scenes/OfficeScene";
import { MAP_COLS, MAP_ROWS, TILE_SIZE } from "@/game/maps/agentmashHq";

export const WORLD_WIDTH = MAP_COLS * TILE_SIZE;
export const WORLD_HEIGHT = MAP_ROWS * TILE_SIZE;

/**
 * The one Phaser.Game factory for the whole app (spec section 2/37: a
 * real game loop that Phaser owns, not React). `PhaserOffice.tsx` is the
 * only caller -- it mounts exactly one instance into a container div and
 * is responsible for tearing it down on unmount.
 */
export function createOfficeGame(parent: HTMLElement): Phaser.Game {
  return new Phaser.Game({
    type: Phaser.AUTO,
    backgroundColor: "#0c0d11",
    scene: [BootScene, OfficeScene],
    fps: { target: 60, min: 20 },
    pixelArt: true,
    render: { pixelArt: true, antialias: false, roundPixels: true },
    scale: {
      mode: Phaser.Scale.RESIZE,
      autoCenter: Phaser.Scale.CENTER_BOTH,
      parent,
      width: "100%",
      height: "100%",
    },
  });
}
