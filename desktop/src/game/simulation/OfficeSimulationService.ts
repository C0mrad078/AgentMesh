import { agentStateMachine, type AgentStateMachine } from "@/game/agents/AgentStateMachine";

/**
 * Spec section 25/51/54: a debug-only service that drives the *same*
 * `AgentStateMachine` real domain events drive -- it never bypasses the
 * state machine, never touches sprites/positions directly, and is not
 * reachable from any production code path (only from `OfficePage`'s
 * Developer Mode panel; AgentMash V2 Phase 4's brief explicitly still
 * allows fixtures there, see docs/agentmash-v2-phase4.md).
 *
 * Phase 4 made this roster-agnostic: it used to target 4 hardcoded
 * character ids that no longer exist as a fixed concept -- it now acts
 * on whichever real agent ids `OfficeDomainAdapter` has already
 * registered for the currently-selected project, so the debug panel
 * stays useful no matter which real agents are on screen.
 */
const SHORT_COOLDOWN_MS = 60_000; // below the default sleep threshold -> sofa
const LONG_COOLDOWN_MS = 10 * 60_000; // above it -> bed

const WORKDAY_TASKS: { title: string; category: "planning" | "designing" | "coding"; provider?: string }[] = [
  { title: "Planejar sprint", category: "planning" },
  { title: "Design Agent Settings", category: "designing", provider: "gemini" },
  { title: "Implement Provider Screen", category: "coding", provider: "codex_cli" },
  { title: "Build ProviderManager", category: "coding", provider: "claude_code_cli" },
];

export class OfficeSimulationService {
  constructor(private readonly sm: AgentStateMachine = agentStateMachine) {}

  private currentAgentIds(): string[] {
    return this.sm.all().map((r) => r.id);
  }

  /** Scenario A -- Workday: every currently-known agent (up to 4 distinct
   * task shapes) gets a real task and walks to their desk to start it. */
  startWorkday(): void {
    this.currentAgentIds().forEach((id, i) => {
      const task = WORKDAY_TASKS[i % WORKDAY_TASKS.length];
      this.sm.apply(id, { type: "task_assigned", taskId: `sim-${i}`, ...task });
    });
  }

  /** Scenario B -- Planning Meeting: everyone walks to the Meeting Room,
   * sits, and (via `endMeeting`) walks back to resume whatever they were
   * doing. */
  startPlanningMeeting(): void {
    for (const id of this.currentAgentIds()) this.sm.apply(id, { type: "meeting_called" });
  }

  endMeeting(): void {
    for (const id of this.currentAgentIds()) this.sm.apply(id, { type: "meeting_ended" });
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
