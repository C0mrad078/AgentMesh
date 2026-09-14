import type { AgentVisualProfile } from "@/game/office-domain/types";

/**
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md "VISUAL PROFILE" /
 * "FALLBACK VISUAL"): the finite set of real, already-rendered character
 * spritesheets the office can actually display (`BootScene` loads exactly
 * these four -- see `game/scenes/BootScene.ts`). This is deliberately
 * *not* the richer skin/hair/outfit breakdown the product brief sketches
 * conceptually: nothing in this codebase renders that yet, so persisting
 * or fabricating it here would be exactly the kind of fake-looking data
 * this project avoids. Multiple real agents legitimately sharing the same
 * preset (there are only 4) are told apart by their real name label, not
 * by a unique appearance -- an explicit, documented limit, not a bug.
 */
export const VISUAL_PRESETS: readonly AgentVisualProfile[] = [
  { preset: "gemini_ceo", textureKey: "gemini_ceo" },
  { preset: "gemini_designer", textureKey: "gemini_designer" },
  { preset: "codex", textureKey: "codex" },
  { preset: "claude_code", textureKey: "claude_code" },
];

const PRESET_BY_KEY = new Map(VISUAL_PRESETS.map((p) => [p.preset, p]));

/** A small, stable, non-cryptographic string hash (FNV-1a variant) --
 * deterministic across runs/reloads, unlike `Math.random()`, which the
 * brief explicitly forbids for this ("o mesmo agente deve manter a mesma
 * aparência após reiniciar o app"). */
export function hashString(value: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Real profile if the agent has one recognized preset persisted; a
 * deterministic (never random) fallback derived from the agent's own id
 * otherwise -- the same agent always resolves to the same preset. */
export function resolveVisualProfile(agentId: string, persisted: Record<string, string>): AgentVisualProfile {
  const persistedPreset = persisted.preset ? PRESET_BY_KEY.get(persisted.preset) : undefined;
  if (persistedPreset) return persistedPreset;
  const index = hashString(agentId) % VISUAL_PRESETS.length;
  return VISUAL_PRESETS[index];
}
