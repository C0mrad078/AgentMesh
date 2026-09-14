import type { AgentDefinition, AvatarAppearance } from "@/game/agents/types";
import { VISUAL_PRESETS } from "@/game/office-domain/visualProfile";
import type { OfficeAgentModel } from "@/game/office-domain/types";

/**
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md): what used to be
 * `AGENT_DEFINITIONS`, a fixed array of exactly 4 named characters, is
 * now `buildAgentDefinition()`, called once per real `OfficeAgentModel`
 * (`game/office-domain/buildOfficeAgents.ts`). The four spritesheets
 * themselves are unchanged (`BootScene` still loads exactly these four --
 * no new art pipeline exists to generate more), so multiple real agents
 * legitimately share one of these four looks; nothing recolors or
 * otherwise fakes a unique appearance for each.
 *
 * Colors are recorded here as CSS hex even though nothing reads them at
 * runtime yet, so a future customization UI has real values to start
 * from instead of reverse-engineering them from pixels (spec section
 * 5/45) -- unchanged from Stage 2.
 */
const APPEARANCE_BY_TEXTURE_KEY: Record<string, AvatarAppearance> = {
  gemini_ceo: {
    skinTone: "#e6c3a0", hairStyle: "short", hairColor: "#231e1e",
    shirt: "#232837", pants: "#191c26", shoes: "#111111", accessory: "tie",
  },
  gemini_designer: {
    skinTone: "#e1b9a5", hairStyle: "beret", hairColor: "#a05ac8",
    shirt: "#d2508f", pants: "#463c6e", shoes: "#2c2440", accessory: "beret",
  },
  codex: {
    skinTone: "#d7af8c", hairStyle: "short", hairColor: "#282320",
    shirt: "#3282c8", pants: "#3c5082", shoes: "#1a1a1a", accessory: "headset",
  },
  claude_code: {
    skinTone: "#ebc8aa", hairStyle: "short", hairColor: "#322822",
    shirt: "#3c785a", pants: "#2d322d", shoes: "#161616", accessory: "glasses",
  },
};

function appearanceFor(textureKey: string): AvatarAppearance {
  return APPEARANCE_BY_TEXTURE_KEY[textureKey] ?? APPEARANCE_BY_TEXTURE_KEY[VISUAL_PRESETS[0].textureKey];
}

/** Builds the one `AgentDefinition` the Phaser layer needs for a real
 * agent -- the sole bridge between `OfficeAgentModel` (domain-shaped) and
 * `Agent`/`Character` (Phaser game objects, spec section 30/37). */
export function buildAgentDefinition(model: OfficeAgentModel, showProjectLabel: boolean): AgentDefinition {
  return {
    id: model.agentId,
    name: model.name,
    role: model.role,
    roleLabel: model.role || model.name,
    textureKey: model.visual.textureKey,
    appearance: appearanceFor(model.visual.textureKey),
    projectLabel: showProjectLabel ? model.projectName : null,
  };
}
