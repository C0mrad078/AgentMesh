import { deriveOfficeSnapshot, type DeriveInput } from "@/office/stateMachine";
import type { AgentState as RealAgentState, VirtualAgent } from "@/office/types";
import { visualAgentFor } from "@/game/agents/realAgentMapping";
import { agentStateMachine, DEFAULT_SLEEP_THRESHOLD_MS, type TaskCategory } from "@/game/agents/AgentStateMachine";
import type { FallbackRecord } from "@/stores/executionStore";
import type { ExecutionStep, ProviderHealthRecord } from "@/types";

/**
 * Stage 3's `VirtualOfficeController` (spec section 6): the one and only
 * bridge between real backend state and the autonomous office. It never
 * decides *what* an agent is doing -- `deriveOfficeSnapshot` (Stage 1,
 * pure, tested) already does that from real agents/steps/provider-health
 * data -- it only translates that real per-(real)-agent state into the
 * right `AgentEvent` for whichever of the 4 visual roles represents it
 * (spec section 12: Phaser/the state machine never invents a state on its
 * own; this class only ever *reacts*).
 *
 * Multiple real agents can map to the same visual role (see
 * `realAgentMapping.ts`); when more than one is genuinely active at once,
 * the most "urgent" real state wins for that frame (spec section 80) --
 * an edge case in practice, since the DAG usually has at most one real
 * agent per role actively stepping at a time.
 */
const STATE_PRIORITY: Record<RealAgentState, number> = {
  ERROR: 9, MEETING: 8, RATE_LIMITED: 7, TESTING: 6, REVIEWING: 6,
  WORKING: 5, PLANNING: 5, WAITING: 4, BLOCKED: 4, RESTING: 3,
  MOVING: 2, COMPLETED: 2, IDLE: 1, OFFLINE: 0,
};

const CATEGORY_BY_RAW: Record<string, TaskCategory> = {
  architecture: "planning", planning: "planning", general: "planning",
  coding: "coding", debugging: "coding", refactoring: "coding",
  research: "designing", documentation: "designing", multimodal: "designing", analysis: "designing",
};

const DEFAULT_CATEGORY_FOR_VISUAL: Record<string, TaskCategory> = {
  agent_gemini_ceo: "planning",
  agent_gemini_designer: "designing",
  agent_codex: "coding",
  agent_claude_code: "coding",
};

function categoryFor(visualAgentId: string, rawCategory: unknown): TaskCategory {
  if (typeof rawCategory === "string" && rawCategory in CATEGORY_BY_RAW) {
    return CATEGORY_BY_RAW[rawCategory];
  }
  return DEFAULT_CATEGORY_FOR_VISUAL[visualAgentId] ?? "coding";
}

interface RealSlot {
  realAgentId: string;
  virtual: VirtualAgent;
  category: unknown;
}

export class RealOfficeAdapter {
  private lastState = new Map<string, RealAgentState>();
  private lastRealOwner = new Map<string, string>();

  sync(input: DeriveInput, fallbacks: Record<string, FallbackRecord> = {}): void {
    const snapshot = deriveOfficeSnapshot(input);
    const stepById = new Map(input.steps.map((s) => [s.id, s]));
    const agentNameById = new Map(input.agents.map((a) => [a.id, a.name]));
    const slots = this.reduceToVisualSlots(snapshot.agents, stepById);

    for (const visualId of Object.keys(DEFAULT_CATEGORY_FOR_VISUAL)) {
      const slot = slots.get(visualId);
      if (!slot) {
        if (this.lastRealOwner.has(visualId)) {
          this.lastRealOwner.delete(visualId);
          this.lastState.delete(visualId);
          agentStateMachine.apply(visualId, { type: "reset" });
        }
        continue;
      }
      this.applyTransition(visualId, slot, input.providerHealth, fallbacks, agentNameById);
    }
  }

  private reduceToVisualSlots(
    agents: Record<string, VirtualAgent>, stepById: Map<string, ExecutionStep>,
  ): Map<string, RealSlot> {
    const best = new Map<string, RealSlot>();
    for (const virtual of Object.values(agents)) {
      const visualId = visualAgentFor(virtual.id);
      if (!visualId) continue;
      const current = best.get(visualId);
      if (current && STATE_PRIORITY[current.virtual.state] >= STATE_PRIORITY[virtual.state]) continue;
      const step = virtual.currentStepId ? stepById.get(virtual.currentStepId) : undefined;
      best.set(visualId, { realAgentId: virtual.id, virtual, category: step?.input?.category });
    }
    return best;
  }

  private applyTransition(
    visualId: string, slot: RealSlot, providerHealth: ProviderHealthRecord[],
    fallbacks: Record<string, FallbackRecord>, agentNameById: Map<string, string>,
  ): void {
    const { virtual, realAgentId } = slot;
    const previous = this.lastState.get(visualId);
    const sameOwner = this.lastRealOwner.get(visualId) === realAgentId;
    this.lastState.set(visualId, virtual.state);
    this.lastRealOwner.set(visualId, realAgentId);

    if (previous === virtual.state && sameOwner) return; // no real change -- never re-issue the same event

    switch (virtual.state) {
      case "PLANNING":
      case "WORKING": {
        if (previous === "MEETING") {
          agentStateMachine.apply(visualId, { type: "meeting_ended" });
          return;
        }
        if (previous === "RATE_LIMITED" || previous === "RESTING") {
          agentStateMachine.apply(visualId, { type: "provider_recovered" });
          return;
        }
        if (previous === "WAITING" || previous === "BLOCKED") {
          agentStateMachine.apply(visualId, { type: "dependency_resolved" });
          return;
        }
        const fallback = fallbacks[realAgentId];
        agentStateMachine.apply(visualId, {
          type: "task_assigned",
          taskId: virtual.currentTaskId ?? realAgentId,
          title: virtual.statusDetail ?? virtual.name,
          category: categoryFor(visualId, slot.category),
          provider: virtual.provider,
          fallbackFrom: fallback ? agentNameById.get(fallback.fromAgentId) ?? fallback.fromAgentId : undefined,
        });
        return;
      }
      case "TESTING":
        agentStateMachine.apply(visualId, { type: "test_started" });
        return;
      case "REVIEWING":
        agentStateMachine.apply(visualId, { type: "review_started" });
        return;
      case "MEETING":
        agentStateMachine.apply(visualId, { type: "meeting_called" });
        return;
      case "WAITING":
      case "BLOCKED":
        agentStateMachine.apply(visualId, { type: "waiting_on_dependency" });
        return;
      case "RATE_LIMITED": {
        const cooldownMs = this.cooldownMsFor(virtual, providerHealth);
        agentStateMachine.apply(visualId, {
          type: "rate_limited", cooldownMs, provider: virtual.provider,
        });
        return;
      }
      case "ERROR":
        agentStateMachine.apply(visualId, { type: "error_occurred", message: virtual.statusDetail ?? undefined });
        return;
      case "COMPLETED":
        agentStateMachine.apply(visualId, { type: "task_completed" });
        return;
      case "IDLE":
      case "OFFLINE":
        // The real agent has no current step (or is deactivated) -- send
        // the visual role back to its own desk with nothing to resume,
        // exactly like the Developer Mode "Reset Office" control.
        agentStateMachine.apply(visualId, { type: "reset" });
        return;
      case "MOVING":
      case "RESTING":
        // `deriveOfficeSnapshot` never actually produces these two as a
        // *current* state (MOVING/RESTING are this office's own visual
        // concepts, not real backend step statuses) -- kept exhaustive
        // only so this switch stays a compile-time check against
        // `AgentState`, not because either is reachable here.
        return;
    }
  }

  /** Spec section 34-36: below the configurable sleep threshold -> short
   * lounge break; at/above it, or when the provider reported no duration
   * at all (an *unknown* rate limit -- spec section 36's own policy) ->
   * the lounge first, same as a short break, never invented as "long". */
  private cooldownMsFor(virtual: VirtualAgent, providerHealth: ProviderHealthRecord[]): number {
    const record = providerHealth.find((h) => h.provider === virtual.provider);
    const retryAfterSeconds = record?.retry_after_seconds;
    if (typeof retryAfterSeconds === "number") return retryAfterSeconds * 1000;
    return DEFAULT_SLEEP_THRESHOLD_MS - 1; // unknown duration -> treated as short (spec section 36)
  }
}

export const realOfficeAdapter = new RealOfficeAdapter();
