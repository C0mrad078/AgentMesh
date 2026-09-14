import { agentStateMachine, type AgentStateMachine } from "@/game/agents/AgentStateMachine";
import { AGENT_DEFINITIONS } from "@/game/agents/appearancePresets";

/**
 * Spec section 25/51/54: a debug-only service that drives the *same*
 * `AgentStateMachine` real Orchestrator events will drive in Stage 3 --
 * it never bypasses the state machine, never touches sprites/positions
 * directly, and is not reachable from any production code path (only
 * from `OfficePage`'s Developer Mode panel). Swapping this out for a
 * real event source in Stage 3 changes zero lines downstream of
 * `AgentStateMachine`.
 */
const ALL_AGENT_IDS = AGENT_DEFINITIONS.map((a) => a.id);
const SHORT_COOLDOWN_MS = 60_000; // below the default sleep threshold -> sofa
const LONG_COOLDOWN_MS = 10 * 60_000; // above it -> bed

export class OfficeSimulationService {
  constructor(private readonly sm: AgentStateMachine = agentStateMachine) {}

  /** Scenario A -- Workday: every agent gets a real task and walks to
   * their desk to start it. */
  startWorkday(): void {
    this.sm.apply("agent_gemini_ceo", { type: "task_assigned", taskId: "sim-plan-1", title: "Planejar sprint", category: "planning" });
    this.sm.apply("agent_gemini_designer", { type: "task_assigned", taskId: "sim-design-1", title: "Design Agent Settings", category: "designing", provider: "gemini" });
    this.sm.apply("agent_codex", { type: "task_assigned", taskId: "sim-fe-1", title: "Implement Provider Screen", category: "coding", provider: "codex_cli" });
    this.sm.apply("agent_claude_code", { type: "task_assigned", taskId: "sim-be-1", title: "Build ProviderManager", category: "coding", provider: "claude_code_cli" });
  }

  /** Scenario B -- Planning Meeting: everyone walks to the Meeting Room,
   * sits, and (via `endMeeting`) walks back to resume whatever they were
   * doing. */
  startPlanningMeeting(): void {
    for (const id of ALL_AGENT_IDS) this.sm.apply(id, { type: "meeting_called" });
  }

  endMeeting(): void {
    for (const id of ALL_AGENT_IDS) this.sm.apply(id, { type: "meeting_ended" });
  }

  /** Scenario C/D -- Rate Limit / Long Cooldown: `cooldownMs` decides
   * sofa vs. bed inside `AgentStateMachine` (spec section 23). */
  rateLimit(agentId: string, cooldownMs: number, provider?: string): void {
    this.sm.apply(agentId, { type: "rate_limited", cooldownMs, provider });
  }

  recover(agentId: string): void {
    this.sm.apply(agentId, { type: "provider_recovered" });
  }

  /** Scenario E -- Testing. */
  sendToTesting(agentId: string): void {
    this.sm.apply(agentId, { type: "test_started" });
  }

  triggerError(agentId: string, message?: string): void {
    this.sm.apply(agentId, { type: "error_occurred", message });
  }

  waitOnDependency(agentId: string): void {
    this.sm.apply(agentId, { type: "waiting_on_dependency" });
  }

  /** Scenario F -- Task Completed. */
  completeTask(agentId: string): void {
    this.sm.apply(agentId, { type: "task_completed" });
  }

  resetOffice(): void {
    this.sm.resetAll();
  }

  /** Convenience for the debug panel's "Rate Limit Codex" / "Long
   * Cooldown Claude" buttons, which name a duration in their label
   * rather than taking one as a parameter. */
  rateLimitShort(agentId: string, provider?: string): void {
    this.rateLimit(agentId, SHORT_COOLDOWN_MS, provider);
  }

  rateLimitLong(agentId: string, provider?: string): void {
    this.rateLimit(agentId, LONG_COOLDOWN_MS, provider);
  }
}

export const officeSimulationService = new OfficeSimulationService();
