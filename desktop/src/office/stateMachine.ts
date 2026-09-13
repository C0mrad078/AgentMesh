import type { Agent, ExecutionStep, ProviderHealthRecord, Task } from "@/types";
import { homeRoomForAgent, roomForCapability } from "@/office/roleMapping";
import { MEETING_SEATS, type AgentState, type DestinationId, type VirtualAgent, type VirtualMeeting } from "@/office/types";

/**
 * Pure derivation: real agents + real execution steps + real provider
 * health -> what every agent is doing right now. No timers, no fake
 * delays -- called again only when a real event/refresh happens (see
 * `officeStore.ts`). This is the one place "spec section 9/10/11"
 * (states + their visual meaning + the rate-limit flow) is decided, so it
 * can be unit-tested without React or Phaser.
 */

const UNHEALTHY_STATUSES = new Set(["degraded", "rate_limited", "unavailable"]);

function latestStepForAgent(steps: ExecutionStep[], agentId: string): ExecutionStep | null {
  const mine = steps.filter((s) => s.kind === "work" && s.agent_id === agentId);
  if (mine.length === 0) return null;
  return mine.reduce((latest, s) => (s.step_index > latest.step_index ? s : latest));
}

function categoryOf(step: ExecutionStep): string {
  const raw = step.input?.category;
  return typeof raw === "string" ? raw : "general";
}

function stateForStep(
  step: ExecutionStep,
  providerHealth: Map<string, string>,
  meetingSeat: DestinationId | null,
): { state: AgentState; destination: DestinationId | null; detail: string | null } {
  if (step.status === "running") {
    if (meetingSeat) {
      return { state: "MEETING", destination: meetingSeat, detail: step.name };
    }
    const health = step.provider ? providerHealth.get(step.provider) : undefined;
    if (health && UNHEALTHY_STATUSES.has(health)) {
      return {
        state: "RATE_LIMITED",
        destination: "lounge",
        detail: `${step.provider} indisponível (${health}) -- aguardando na Lounge`,
      };
    }
    const category = categoryOf(step);
    const destination = roomForCapability(category, step.agent_id ?? "");
    const stateByCategory: Partial<Record<string, AgentState>> = {
      testing: "TESTING",
      security: "TESTING",
      architecture: "PLANNING",
      planning: "PLANNING",
    };
    return {
      state: stateByCategory[category] ?? "WORKING",
      destination,
      detail: step.name,
    };
  }
  if (step.status === "pending") {
    return { state: "WAITING", destination: null, detail: "Aguardando dependência" };
  }
  if (step.status === "failed") {
    return { state: "ERROR", destination: null, detail: step.error ? String(step.error.message ?? "Erro") : "Erro" };
  }
  if (step.status === "cancelled") {
    return { state: "IDLE", destination: null, detail: null };
  }
  // completed
  return { state: "COMPLETED", destination: null, detail: step.name };
}

export interface DeriveInput {
  agents: Agent[];
  steps: ExecutionStep[];
  providerHealth: ProviderHealthRecord[];
  activeTask: Task | null;
}

export function deriveOfficeSnapshot({
  agents, steps, providerHealth, activeTask,
}: DeriveInput): { agents: Record<string, VirtualAgent>; meetings: VirtualMeeting[] } {
  const healthByProvider = new Map(providerHealth.map((h) => [h.provider, h.status]));
  const isDebateLike = activeTask?.mode === "debate" || activeTask?.mode === "consensus";

  const runningWorkSteps = steps.filter((s) => s.kind === "work" && s.status === "running");
  const distinctRunningAgents = new Set(runningWorkSteps.map((s) => s.agent_id).filter(Boolean));
  const meetingActive = isDebateLike && distinctRunningAgents.size >= 2;

  // Deterministic seat assignment (sorted agent id -> seat index) so two
  // participants never land on the same tile (spec section 39) and the
  // same agent keeps its seat across re-derivations of an unchanged
  // meeting. Beyond four participants, extras share the room's general
  // point rather than crash or silently drop someone.
  const seatByAgentId = new Map<string, DestinationId>();
  if (meetingActive) {
    [...distinctRunningAgents]
      .filter((id): id is string => Boolean(id))
      .sort()
      .forEach((id, index) => {
        seatByAgentId.set(id, MEETING_SEATS[index] ?? "meeting_room");
      });
  }

  const meetings: VirtualMeeting[] = meetingActive
    ? [{
        id: `meeting_${activeTask!.id}`,
        title: activeTask!.title,
        participantAgentIds: [...distinctRunningAgents] as string[],
        relatedStepIds: runningWorkSteps.map((s) => s.id),
        status: "active",
      }]
    : [];

  const result: Record<string, VirtualAgent> = {};
  for (const agent of agents) {
    const homeRoom = homeRoomForAgent(agent);
    if (!agent.active) {
      result[agent.id] = {
        id: agent.id, name: agent.name, role: agent.name, provider: agent.provider, model: agent.model,
        homeRoom, state: "OFFLINE", currentTaskId: null, currentStepId: null, currentExecutionId: null,
        destination: null, statusDetail: "Agente desativado", progress: null, lastActivityAt: null, retryAt: null,
      };
      continue;
    }

    const step = latestStepForAgent(steps, agent.id);
    if (!step) {
      result[agent.id] = {
        id: agent.id, name: agent.name, role: agent.name, provider: agent.provider, model: agent.model,
        homeRoom, state: "IDLE", currentTaskId: null, currentStepId: null, currentExecutionId: null,
        destination: null, statusDetail: null, progress: null, lastActivityAt: null, retryAt: null,
      };
      continue;
    }

    const meetingSeat = seatByAgentId.get(agent.id) ?? null;
    const { state, destination, detail } = stateForStep(step, healthByProvider, meetingSeat);
    result[agent.id] = {
      id: agent.id,
      name: agent.name,
      role: agent.name,
      provider: step.provider ?? agent.provider,
      model: agent.model,
      homeRoom,
      state,
      currentTaskId: activeTask?.id ?? null,
      currentStepId: step.id,
      currentExecutionId: step.execution_id,
      destination,
      statusDetail: detail,
      progress: null,
      lastActivityAt: step.started_at,
      retryAt: null,
    };
  }

  return { agents: result, meetings };
}
