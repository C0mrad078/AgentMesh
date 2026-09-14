import Phaser from "phaser";
import { Character, characterDepth } from "@/game/entities/Character";
import { destinationPoint } from "@/game/maps/agentmashHq";
import { navigationService, type GridPosition } from "@/game/systems/NavigationService";
import type { AgentDefinition, AgentRuntimeState } from "@/game/agents/types";
import { animationFor, type StatusIcon } from "@/game/agents/AgentStateMachine";

const ICON_FRAME: Record<Exclude<StatusIcon, null>, number> = {
  sleeping: 0, error: 1, thinking: 2, waiting: 3, coffee: 4, celebrate: 5,
};

/**
 * One autonomous, state-driven character (Gemini CEO, Gemini Designer,
 * Codex, or Claude Code). Never user-controlled (spec section 30) --
 * the only inputs it accepts are `applyRuntimeState()` calls forwarded
 * from `AgentStateMachine` by `OfficeScene`. Movement always goes
 * through `NavigationService.findPath`, exactly like every other walking
 * entity in this codebase; nothing here ever assigns a position directly.
 */
export class Agent extends Character {
  private pose: "walk" | "seat" | "lying" | "celebrate" | "idle" = "idle";
  private readonly nameLabel: Phaser.GameObjects.Text;
  private readonly icon: Phaser.GameObjects.Sprite;
  private lastDestinationTile: GridPosition | null = null;

  constructor(scene: Phaser.Scene, public readonly definition: AgentDefinition, startTile: GridPosition) {
    super(scene, definition.textureKey, startTile, 3.2);

    this.nameLabel = scene.add.text(this.sprite.x, this.sprite.y - 50, definition.name, {
      fontSize: "9px", color: "#e5e7eb", fontFamily: "monospace",
    }).setOrigin(0.5, 0);

    this.icon = scene.add.sprite(this.sprite.x, this.sprite.y - 56, "status_icons", 0).setVisible(false);
    this.syncOverlays();
    this.playRestPose(); // see the comment in Character's constructor
  }

  protected playRestPose(): void {
    switch (this.pose) {
      case "seat":
        this.sprite.play(`${this.definition.textureKey}_seat_${this.direction}`, true);
        return;
      case "lying":
        this.sprite.play(`${this.definition.textureKey}_lying`, true);
        return;
      case "celebrate":
        this.sprite.play(`${this.definition.textureKey}_celebrate`, true);
        return;
      default:
        this.sprite.play(`${this.definition.textureKey}_idle_${this.direction}`, true);
    }
  }

  /** Spec section 8/9: the agent's physical position is a direct
   * consequence of its state, resolved to a destination tile by
   * `AgentStateMachine`. If already there, only the pose/icon change
   * (no pointless re-path); otherwise it walks there via real A* --
   * cancelling whatever it was doing before (spec section 60). */
  applyRuntimeState(runtime: AgentRuntimeState): void {
    // "MOVING" is deliberately never stored in `AgentRuntimeState.state`
    // (see AgentStateMachine.ts) -- while `isMoving` is true, `Character`
    // is already playing its walk animation directly; the pose computed
    // here is what plays once the walk finishes (spec section 8: the
    // agent's *arrival* pose reflects its real state).
    const plan = animationFor(runtime.state);
    this.pose = plan.pose;
    this.setIcon(plan.icon);

    if (runtime.destination) {
      const [dx, dy] = destinationPoint(runtime.destination);
      const goal: GridPosition = { x: dx, y: dy };
      const current = this.tilePosition;
      const alreadyThere = current.x === goal.x && current.y === goal.y;
      const alreadyHeaded = this.lastDestinationTile?.x === goal.x && this.lastDestinationTile?.y === goal.y;

      if (alreadyThere) {
        this.lastDestinationTile = goal;
        if (!this.isMoving) this.playRestPose();
        return;
      }
      if (alreadyHeaded && this.isMoving) return; // already en route, don't re-path every tick

      this.lastDestinationTile = goal;
      const path = navigationService.findPath(current, goal);
      if (path) {
        this.moveAlongPath(path);
      }
      return;
    }

    if (!this.isMoving) this.playRestPose();
  }

  private setIcon(icon: StatusIcon): void {
    if (!icon) {
      this.icon.setVisible(false);
      return;
    }
    this.icon.setFrame(ICON_FRAME[icon]);
    this.icon.setVisible(true);
  }

  private syncOverlays(): void {
    this.nameLabel.setPosition(this.sprite.x, this.sprite.y - 50);
    this.nameLabel.setDepth(characterDepth(this.sprite.y) + 1);
    this.icon.setPosition(this.sprite.x, this.sprite.y - 56);
    this.icon.setDepth(characterDepth(this.sprite.y) + 1);
  }

  update(deltaMs: number): void {
    super.update(deltaMs);
    this.syncOverlays();
    // The path-following in `Character.update` plays the walk animation
    // directly; once it settles back to "not moving" it calls
    // `playRestPose()` (overridden above), so nothing else is needed
    // here besides keeping the label/icon glued to the sprite.
  }

  destroy(): void {
    this.nameLabel.destroy();
    this.icon.destroy();
    super.destroy();
  }
}
