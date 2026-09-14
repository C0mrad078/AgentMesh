import Phaser from "phaser";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;

/**
 * Spec section 22/45 ("Camera Controller"): owns every camera concern
 * (follow, zoom, pan, bounds, reset) in one place instead of scattering
 * wheel/drag handlers across the scene.
 */
export class CameraController {
  private following = false;

  constructor(
    private readonly scene: Phaser.Scene,
    private readonly worldWidth: number,
    private readonly worldHeight: number,
  ) {
    const cam = scene.cameras.main;
    cam.setBounds(0, 0, worldWidth, worldHeight);
    cam.setZoom(1);

    scene.input.on("wheel", (_p: unknown, _go: unknown, _dx: number, dy: number) => {
      this.zoomBy(-dy * 0.001);
    });

    let dragStart: { x: number; y: number } | null = null;
    scene.input.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      if (pointer.rightButtonDown() || pointer.middleButtonDown()) {
        dragStart = { x: pointer.x, y: pointer.y };
      }
    });
    scene.input.on("pointermove", (pointer: Phaser.Input.Pointer) => {
      if (!dragStart || !(pointer.rightButtonDown() || pointer.middleButtonDown())) return;
      this.stopFollow();
      cam.scrollX -= (pointer.x - dragStart.x) / cam.zoom;
      cam.scrollY -= (pointer.y - dragStart.y) / cam.zoom;
      dragStart = { x: pointer.x, y: pointer.y };
    });
    scene.input.on("pointerup", () => {
      dragStart = null;
    });
  }

  private get cam(): Phaser.Cameras.Scene2D.Camera {
    return this.scene.cameras.main;
  }

  follow(target: Phaser.GameObjects.GameObject & { x: number; y: number }): void {
    this.cam.startFollow(target, true, 0.15, 0.15);
    this.following = true;
  }

  stopFollow(): void {
    this.cam.stopFollow();
    this.following = false;
  }

  isFollowing(): boolean {
    return this.following;
  }

  zoomBy(delta: number): void {
    const next = Phaser.Math.Clamp(this.cam.zoom + delta, MIN_ZOOM, MAX_ZOOM);
    this.cam.setZoom(next);
  }

  fit(): void {
    this.stopFollow();
    const zoom = Math.min(this.cam.width / this.worldWidth, this.cam.height / this.worldHeight);
    this.cam.setZoom(Phaser.Math.Clamp(zoom, MIN_ZOOM, MAX_ZOOM));
    this.cam.centerOn(this.worldWidth / 2, this.worldHeight / 2);
  }

  reset(): void {
    this.stopFollow();
    this.cam.setZoom(1);
    this.cam.centerOn(this.worldWidth / 2, this.worldHeight / 2);
  }

  centerOn(x: number, y: number): void {
    this.cam.centerOn(x, y);
  }
}
