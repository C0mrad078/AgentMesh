/**
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md): the shape the
 * Pixel Office actually consumes. Built once, by `buildOfficeAgents()`,
 * from real `Agent`/`Team`/`Session` domain records -- Phaser never sees
 * an `Agent`/`Team`/`Session` object directly (`OfficeScene` imports
 * nothing from `@/types`, `@/services`, or `@/stores`).
 */

/** Minimal, honest set for this phase -- no runtime exists yet to
 * produce anything richer (no TESTING/REVIEWING/MEETING; those return in
 * Phase 5+ once real session events drive them). */
export type OfficePresenceState = "OFFLINE" | "AVAILABLE" | "IDLE" | "WORKING" | "WAITING" | "ERROR";

export interface AgentVisualProfile {
  preset: string;
  textureKey: string;
}

export interface OfficeAgentModel {
  agentId: string;
  name: string;
  role: string;

  projectId: string | null;
  projectName: string | null;

  teamId: string | null;
  teamName: string | null;

  sessionId: string | null;

  state: OfficePresenceState;
  visual: AgentVisualProfile;
}
