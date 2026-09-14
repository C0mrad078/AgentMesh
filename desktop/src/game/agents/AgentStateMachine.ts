import { AGENT_DEFINITIONS, agentDefinition } from "@/game/agents/appearancePresets";
import { initialRuntimeState, type AgentRuntimeState, type AgentState, type DestinationId } from "@/game/agents/types";
import { workstationSystem } from "@/game/systems/WorkstationSystem";
import { bedSystem } from "@/game/systems/BedSystem";
import { sofaSystem } from "@/game/systems/SofaSystem";
import { meetingRoomSystem } from "@/game/systems/MeetingRoomSystem";

/**
 * Spec section 55: `SimulationService -> AgentEvent -> AgentStateMachine
 * -> VirtualOfficeController -> Movement/Animation`. This module is that
 * middle step -- the single authority for "given this event, what state
 * is the agent in now, and where does their body belong". Stage 3 will
 * feed it real Orchestrator events instead of `OfficeSimulationService`
 * ones; nothing here needs to change for that swap.
 */

export type TaskCategory = "coding" | "designing" | "researching" | "planning";

export type AgentEvent =
  | { type: "task_assigned"; taskId: string; title: string; category: TaskCategory; provider?: string; fallbackFrom?: string }
  | { type: "meeting_called" }
  | { type: "meeting_ended" }
  | { type: "waiting_on_dependency" }
  | { type: "dependency_resolved" }
  | { type: "test_started" }
  | { type: "review_started" }
  | { type: "rate_limited"; cooldownMs: number; provider?: string }
  | { type: "provider_recovered" }
  | { type: "error_occurred"; message?: string }
  | { type: "task_completed" }
  | { type: "reset" };

const CATEGORY_STATE: Record<TaskCategory, AgentState> = {
  coding: "CODING", designing: "DESIGNING", researching: "RESEARCHING", planning: "PLANNING",
};

/** Configurable per spec section 23 -- a cooldown at or above this
 * duration sends the agent to bed instead of the sofa. */
export const DEFAULT_SLEEP_THRESHOLD_MS = 5 * 60 * 1000;

export type Pose = "walk" | "seat" | "lying" | "celebrate" | "idle";
export type StatusIcon = "sleeping" | "error" | "thinking" | "waiting" | "coffee" | "celebrate" | null;

export interface AnimationPlan {
  pose: Pose;
  icon: StatusIcon;
}

/** Spec section 58 ("Mapa de estado -> animação"), centralized in one
 * table instead of scattered `if (state === ...)` checks. */
const STATE_ANIMATION: Record<AgentState, AnimationPlan> = {
  OFFLINE: { pose: "idle", icon: null },
  IDLE: { pose: "seat", icon: null },
  MOVING: { pose: "walk", icon: null },
  PLANNING: { pose: "seat", icon: "thinking" },
  WORKING: { pose: "seat", icon: null },
  CODING: { pose: "seat", icon: null },
  DESIGNING: { pose: "seat", icon: null },
  RESEARCHING: { pose: "seat", icon: "thinking" },
  TESTING: { pose: "seat", icon: null },
  REVIEWING: { pose: "seat", icon: "thinking" },
  MEETING: { pose: "seat", icon: "thinking" },
  WAITING: { pose: "idle", icon: "waiting" },
  BLOCKED: { pose: "idle", icon: "waiting" },
  RATE_LIMITED: { pose: "idle", icon: "waiting" },
  COOLDOWN: { pose: "idle", icon: "waiting" },
  RESTING: { pose: "seat", icon: "coffee" },
  SLEEPING: { pose: "lying", icon: "sleeping" },
  ERROR: { pose: "idle", icon: "error" },
  COMPLETED: { pose: "celebrate", icon: "celebrate" },
};

export function animationFor(state: AgentState): AnimationPlan {
  return STATE_ANIMATION[state];
}

interface AgentRecord {
  runtime: AgentRuntimeState;
  savedTask: { taskId: string; title: string; category: TaskCategory; provider?: string } | null;
}

type Listener = (agentId: string, runtime: AgentRuntimeState, destination: DestinationId | null) => void;

/**
 * Owns every agent's current `AgentRuntimeState` and resolves each
 * incoming `AgentEvent` into {state, destination}, claiming/releasing
 * desks, meeting seats, sofa seats, and beds through the shared
 * `OccupancySystem` as it goes (spec section 40). Pure TypeScript --
 * no Phaser dependency, so it's directly unit-testable.
 */
export class AgentStateMachine {
  private records = new Map<string, AgentRecord>();
  private listeners = new Set<Listener>();
  sleepThresholdMs = DEFAULT_SLEEP_THRESHOLD_MS;

  constructor() {
    for (const agent of AGENT_DEFINITIONS) {
      this.records.set(agent.id, { runtime: initialRuntimeState(agent.id), savedTask: null });
    }
  }

  onChange(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get(agentId: string): AgentRuntimeState | undefined {
    return this.records.get(agentId)?.runtime;
  }

  all(): AgentRuntimeState[] {
    return [...this.records.values()].map((r) => r.runtime);
  }

  /** Sends every agent to their own desk, IDLE, with no saved task --
   * spec section 53's "Reset Office" debug control. */
  resetAll(): void {
    for (const agentId of this.records.keys()) this.apply(agentId, { type: "reset" });
  }

  apply(agentId: string, event: AgentEvent): void {
    const record = this.records.get(agentId);
    const def = agentDefinition(agentId);
    if (!record || !def) return;

    const prev = record.runtime;
    let state: AgentState = prev.state;
    let destination: DestinationId | null = prev.destination;
    let taskId = prev.taskId;
    let taskTitle = prev.taskTitle;
    let provider = prev.provider;
    let detail = prev.detail;
    let fallbackFrom = prev.fallbackFrom;

    // Any explicit event releases whatever transient spot (meeting seat,
    // sofa, bed) the agent was in before -- the desk is released too
    // except when the event keeps them at their own desk (spec section
    // 60: never leave a stale reservation behind when redirected).
    switch (event.type) {
      case "task_assigned": {
        state = CATEGORY_STATE[event.category];
        taskId = event.taskId;
        taskTitle = event.title;
        provider = event.provider ?? provider;
        detail = event.title;
        fallbackFrom = event.fallbackFrom ?? null;
        record.savedTask = { taskId: event.taskId, title: event.title, category: event.category, provider: event.provider };
        meetingRoomSystem.release(agentId);
        sofaSystem.release(agentId);
        bedSystem.release(agentId);
        workstationSystem.claim(agentId);
        destination = def.homeDesk;
        break;
      }
      case "meeting_called": {
        state = "MEETING";
        detail = "Reunião de planejamento";
        workstationSystem.release(agentId);
        const seat = meetingRoomSystem.claimAny(agentId);
        destination = seat?.id as DestinationId | null ?? "meeting_room";
        break;
      }
      case "meeting_ended": {
        meetingRoomSystem.release(agentId);
        workstationSystem.claim(agentId);
        destination = def.homeDesk;
        if (record.savedTask) {
          state = CATEGORY_STATE[record.savedTask.category];
          taskId = record.savedTask.taskId;
          taskTitle = record.savedTask.title;
          detail = record.savedTask.title;
        } else {
          state = "IDLE";
          detail = null;
        }
        break;
      }
      case "waiting_on_dependency": {
        state = "WAITING";
        detail = "Aguardando dependência";
        break;
      }
      case "dependency_resolved": {
        if (record.savedTask) {
          state = CATEGORY_STATE[record.savedTask.category];
          detail = record.savedTask.title;
        } else {
          state = "IDLE";
          detail = null;
        }
        break;
      }
      case "test_started": {
        state = "TESTING";
        detail = "Executando testes";
        workstationSystem.release(agentId);
        destination = "testing_lab";
        break;
      }
      case "review_started": {
        state = "REVIEWING";
        detail = "Revisando";
        workstationSystem.release(agentId);
        destination = "testing_lab";
        break;
      }
      case "rate_limited": {
        // Spec section 20/23: short cooldown -> Lounge sofa, long cooldown
        // (>= configurable threshold) -> Recovery Room bed. The
        // *resolved* visual state is always RESTING or SLEEPING -- never
        // a bare "RATE_LIMITED" left unrendered.
        workstationSystem.release(agentId);
        provider = event.provider ?? provider;
        if (event.cooldownMs >= this.sleepThresholdMs) {
          state = "SLEEPING";
          detail = `${provider ?? "Provider"} indisponível -- cooldown longo`;
          const bed = bedSystem.claimAny(agentId);
          destination = (bed?.id as DestinationId | null) ?? "recovery_room";
        } else {
          state = "RESTING";
          detail = `${provider ?? "Provider"} indisponível -- cooldown curto`;
          const seat = sofaSystem.claimAny(agentId);
          destination = (seat?.id as DestinationId | null) ?? "lounge";
        }
        break;
      }
      case "provider_recovered": {
        sofaSystem.release(agentId);
        bedSystem.release(agentId);
        workstationSystem.claim(agentId);
        destination = def.homeDesk;
        if (record.savedTask) {
          state = CATEGORY_STATE[record.savedTask.category];
          taskId = record.savedTask.taskId;
          taskTitle = record.savedTask.title;
          detail = record.savedTask.title;
        } else {
          state = "IDLE";
          detail = null;
        }
        break;
      }
      case "error_occurred": {
        state = "ERROR";
        detail = event.message ?? "Erro";
        break;
      }
      case "task_completed": {
        state = "COMPLETED";
        detail = taskTitle;
        this.scheduleSettle(agentId);
        break;
      }
      case "reset": {
        meetingRoomSystem.release(agentId);
        sofaSystem.release(agentId);
        bedSystem.release(agentId);
        workstationSystem.claim(agentId);
        state = "IDLE";
        destination = def.homeDesk;
        taskId = null;
        taskTitle = null;
        detail = null;
        provider = null;
        fallbackFrom = null;
        record.savedTask = null;
        break;
      }
    }

    record.runtime = {
      id: agentId, state, destination, taskId, taskTitle, provider,
      progress: prev.progress, detail, fallbackFrom, version: prev.version + 1,
    };
    for (const listener of this.listeners) listener(agentId, record.runtime, destination);
  }

  /** Spec section 28: `COMPLETED -> celebrate -> IDLE`. The celebration
   * is a real, timed transition of the state machine itself (not a
   * decorative canvas effect) -- after it settles, the agent is simply
   * idle at their own desk again, ready for the next task. */
  private scheduleSettle(agentId: string): void {
    setTimeout(() => {
      const record = this.records.get(agentId);
      if (!record || record.runtime.state !== "COMPLETED") return; // superseded by a newer event
      record.savedTask = null;
      record.runtime = {
        ...record.runtime, state: "IDLE", taskId: null, taskTitle: null, detail: null,
        fallbackFrom: null, version: record.runtime.version + 1,
      };
      for (const listener of this.listeners) listener(agentId, record.runtime, record.runtime.destination);
    }, 2200);
  }
}

export const agentStateMachine = new AgentStateMachine();
