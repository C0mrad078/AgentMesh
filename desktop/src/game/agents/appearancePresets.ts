import type { AgentDefinition } from "@/game/agents/types";

/**
 * Must stay in sync with the `PRESETS` dict in
 * `scripts/generate_office_assets.py`, which bakes each of these into a
 * real spritesheet (`<textureKey>.png`). Colors are recorded here as CSS
 * hex too, even though nothing reads them at runtime yet, so a future
 * customization UI has real values to start from instead of reverse
 * -engineering them from pixels (spec section 5/45).
 */
export const AGENT_DEFINITIONS: AgentDefinition[] = [
  {
    id: "agent_gemini_ceo",
    name: "Gemini CEO",
    role: "ceo",
    roleLabel: "CEO / Orchestrator",
    textureKey: "gemini_ceo",
    homeDesk: "ceo_office",
    homeRoom: "ceo_office",
    appearance: {
      skinTone: "#e6c3a0", hairStyle: "short", hairColor: "#231e1e",
      shirt: "#232837", pants: "#191c26", shoes: "#111111", accessory: "tie",
    },
  },
  {
    id: "agent_gemini_designer",
    name: "Gemini Designer",
    role: "designer",
    roleLabel: "UI/UX Designer",
    textureKey: "gemini_designer",
    homeDesk: "design_desk",
    homeRoom: "design_desk",
    appearance: {
      skinTone: "#e1b9a5", hairStyle: "beret", hairColor: "#a05ac8",
      shirt: "#d2508f", pants: "#463c6e", shoes: "#2c2440", accessory: "beret",
    },
  },
  {
    id: "agent_codex",
    name: "Codex",
    role: "frontend_developer",
    roleLabel: "Frontend Developer",
    textureKey: "codex",
    homeDesk: "frontend_desk",
    homeRoom: "frontend_desk",
    appearance: {
      skinTone: "#d7af8c", hairStyle: "short", hairColor: "#282320",
      shirt: "#3282c8", pants: "#3c5082", shoes: "#1a1a1a", accessory: "headset",
    },
  },
  {
    id: "agent_claude_code",
    name: "Claude Code",
    role: "backend_developer",
    roleLabel: "Backend Developer",
    textureKey: "claude_code",
    homeDesk: "backend_desk",
    homeRoom: "backend_desk",
    appearance: {
      skinTone: "#ebc8aa", hairStyle: "short", hairColor: "#322822",
      shirt: "#3c785a", pants: "#2d322d", shoes: "#161616", accessory: "glasses",
    },
  },
];

export function agentDefinition(id: string): AgentDefinition | undefined {
  return AGENT_DEFINITIONS.find((a) => a.id === id);
}
