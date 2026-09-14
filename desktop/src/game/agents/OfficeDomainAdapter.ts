import { agentStateMachine, type TaskCategory } from "@/game/agents/AgentStateMachine";
import { officeRosterStore } from "@/game/agents/officeRosterStore";
import type { OfficeAgentModel, OfficePresenceState } from "@/game/office-domain/types";

/**
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md "DOMAIN → OFFICE
 * ADAPTER"): the successor to Stage 3's `RealOfficeAdapter`, which
 * compressed many real *routing* agent ids down onto 4 fixed visual
 * characters (`realAgentMapping.ts`, deleted this phase). That
 * compression no longer exists to do: every real, persisted `Agent` a
 * project has *is* its own office character now, 1:1, up to
 * `WORKSTATION_CAPACITY` desks. This class only ever reacts to a
 * `OfficeAgentModel[]` it is given (produced by the pure
 * `buildOfficeAgents()`) -- it never touches Phaser, a repository, or the
 * bridge itself (spec "NÃO ACOPLAR PHASER AO BACKEND").
 */
function inferCategory(role: string): TaskCategory {
  const lower = role.toLowerCase();
  if (lower.includes("design")) return "designing";
  if (lower.includes("research") || lower.includes("analy") || lower.includes("pesquis")) return "researching";
  if (lower.includes("architect") || lower.includes("plan") || lower.includes("arquitet")) return "planning";
  return "coding";
}

export class OfficeDomainAdapter {
  private lastState = new Map<string, OfficePresenceState>();

  /** Reconciles the state machine (and, via `officeRosterStore`, the
   * Phaser layer) against the real roster this frame. Idempotent to call
   * repeatedly with the same input -- only genuine changes (a new agent,
   * a removed one, or a real state transition) touch anything. */
  sync(models: OfficeAgentModel[], showProjectLabels: boolean): void {
    const nextIds = new Set(models.map((m) => m.agentId));
    for (const agentId of this.lastState.keys()) {
      if (!nextIds.has(agentId)) {
        agentStateMachine.removeAgent(agentId);
        this.lastState.delete(agentId);
      }
    }

    for (const model of models) {
      const previousState = this.lastState.get(model.agentId);
      const isNew = previousState === undefined;
      if (isNew) agentStateMachine.ensureAgent(model.agentId);
      if (isNew || previousState !== model.state) {
        this.applyTransition(model);
        this.lastState.set(model.agentId, model.state);
      }
    }

    officeRosterStore.set({ models, showProjectLabels });
  }

  private applyTransition(model: OfficeAgentModel): void {
    switch (model.state) {
      case "WORKING":
        agentStateMachine.apply(model.agentId, {
          type: "task_assigned",
          taskId: model.sessionId ?? model.agentId,
          // Honest placeholder: no runtime exists yet to report *what*
          // the active session is doing (Phase 5+) -- never a fabricated
          // task description, just an honest "there is a real session".
          title: "Sessão ativa",
          category: inferCategory(model.role),
        });
        return;
      case "WAITING":
        agentStateMachine.apply(model.agentId, { type: "waiting_on_dependency" });
        return;
      case "ERROR":
        agentStateMachine.apply(model.agentId, { type: "error_occurred" });
        return;
      case "AVAILABLE":
      case "IDLE":
      case "OFFLINE":
        agentStateMachine.apply(model.agentId, { type: "reset" });
        return;
    }
  }
}

export const officeDomainAdapter = new OfficeDomainAdapter();
