import Phaser from "phaser";
import tilesetUrl from "@/game/assets/tileset.png";
import statusIconsUrl from "@/game/assets/status_icons.png";
import geminiCeoUrl from "@/game/assets/gemini_ceo.png";
import geminiDesignerUrl from "@/game/assets/gemini_designer.png";
import codexUrl from "@/game/assets/codex.png";
import claudeCodeUrl from "@/game/assets/claude_code.png";
import { RAW_TILED_MAP } from "@/game/maps/agentmashHq";

/**
 * Spec section 67 ("MapLoader"): loads the real tileset image, the
 * status-icon glyph atlas, all four named agent spritesheets, and
 * registers the real Tiled JSON map -- nothing here draws anything;
 * `OfficeScene` does that once every asset is confirmed loaded.
 */
export class BootScene extends Phaser.Scene {
  constructor() {
    super("BootScene");
  }

  preload(): void {
    // Loaded as a spritesheet (not a plain image) so individual tile ids
    // are addressable as frames -- both for the Tiled tilemap layers and
    // for standalone interactive-object sprites (the Computer icon, etc.)
    // that reuse the same atlas.
    this.load.spritesheet("tileset", tilesetUrl, { frameWidth: 32, frameHeight: 32 });
    this.load.spritesheet("status_icons", statusIconsUrl, { frameWidth: 16, frameHeight: 16 });
    this.load.spritesheet("gemini_ceo", geminiCeoUrl, { frameWidth: 32, frameHeight: 48 });
    this.load.spritesheet("gemini_designer", geminiDesignerUrl, { frameWidth: 32, frameHeight: 48 });
    this.load.spritesheet("codex", codexUrl, { frameWidth: 32, frameHeight: 48 });
    this.load.spritesheet("claude_code", claudeCodeUrl, { frameWidth: 32, frameHeight: 48 });
  }

  create(): void {
    this.cache.tilemap.add("office", { format: Phaser.Tilemaps.Formats.TILED_JSON, data: RAW_TILED_MAP });
    this.scene.start("OfficeScene");
  }
}
