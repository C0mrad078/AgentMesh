import type { OfficeAgentModel } from "@/game/office-domain/types";

export interface OfficeRoster {
  models: OfficeAgentModel[];
  /** True only in "All Projects" view (multiple projects visible at
   * once) -- `OfficeScene` shows a small project-name label under each
   * agent's name only then, never as a color change (the brief
   * explicitly forbids recoloring a character to indicate its project). */
  showProjectLabels: boolean;
}

type Listener = (roster: OfficeRoster) => void;

const EMPTY_ROSTER: OfficeRoster = { models: [], showProjectLabels: false };

/**
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md "DOMAIN → OFFICE
 * ADAPTER" / "NÃO ACOPLAR PHASER AO BACKEND"): the one channel real
 * domain data reaches `OfficeScene` through. `OfficeDomainAdapter`
 * (React-hook-driven) is the only writer; `OfficeScene` is the only
 * Phaser-side reader -- mirrors the existing `agentStateMachine` singleton
 * pattern exactly, so the scene never imports anything from `@/services`,
 * `@/stores`, or `@/types` directly.
 */
class OfficeRosterStore {
  private roster: OfficeRoster = EMPTY_ROSTER;
  private listeners = new Set<Listener>();

  set(roster: OfficeRoster): void {
    this.roster = roster;
    for (const listener of this.listeners) listener(roster);
  }

  get(): OfficeRoster {
    return this.roster;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

export const officeRosterStore = new OfficeRosterStore();
