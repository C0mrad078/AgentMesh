import { describe, expect, it, beforeEach, vi } from "vitest";
import { AgentStateMachine } from "@/game/agents/AgentStateMachine";
import { AGENT_DEFINITIONS } from "@/game/agents/appearancePresets";
import { workstationSystem } from "@/game/systems/WorkstationSystem";
import { bedSystem } from "@/game/systems/BedSystem";
import { sofaSystem } from "@/game/systems/SofaSystem";
import { meetingRoomSystem } from "@/game/systems/MeetingRoomSystem";

const CEO = "agent_gemini_ceo";
const DESIGNER = "agent_gemini_designer";
const CODEX = "agent_codex";
const CLAUDE = "agent_claude_code";

// The occupancy systems (beds/sofa/meeting seats/desks) are shared
// singletons -- release every agent from all of them between tests so
// state from one test never leaks into the next.
function resetOccupancy() {
  for (const { id } of AGENT_DEFINITIONS) {
    workstationSystem.release(id);
    bedSystem.release(id);
    sofaSystem.release(id);
    meetingRoomSystem.release(id);
  }
}

describe("AgentStateMachine", () => {
  let sm: AgentStateMachine;

  beforeEach(() => {
    resetOccupancy();
    sm = new AgentStateMachine();
  });

  it("starts every agent IDLE with no destination", () => {
    for (const { id } of AGENT_DEFINITIONS) {
      expect(sm.get(id)?.state).toBe("IDLE");
    }
  });

  it("task_assigned sends the agent to their own desk in the right work state (spec section 8/9/10/11)", () => {
    sm.apply(CODEX, { type: "task_assigned", taskId: "t1", title: "Implement Provider Screen", category: "coding", provider: "codex_cli" });
    const runtime = sm.get(CODEX)!;
    expect(runtime.state).toBe("CODING");
    expect(runtime.destination).toBe("frontend_desk");
    expect(runtime.taskTitle).toBe("Implement Provider Screen");
    expect(runtime.provider).toBe("codex_cli");
  });

  it("designer gets DESIGNING, CEO gets PLANNING, from the same event shape", () => {
    sm.apply(DESIGNER, { type: "task_assigned", taskId: "t2", title: "Design Agent Settings", category: "designing" });
    expect(sm.get(DESIGNER)!.state).toBe("DESIGNING");
    sm.apply(CEO, { type: "task_assigned", taskId: "t3", title: "Plan sprint", category: "planning" });
    expect(sm.get(CEO)!.state).toBe("PLANNING");
  });

  it("meeting_called moves every agent to a distinct real meeting seat (spec section 14/15/39)", () => {
    for (const { id } of AGENT_DEFINITIONS) sm.apply(id, { type: "meeting_called" });
    const destinations = AGENT_DEFINITIONS.map((a) => sm.get(a.id)!.destination);
    expect(new Set(destinations).size).toBe(4); // no two agents share a seat
    for (const d of destinations) expect(d).toMatch(/^meeting_seat_0/);
    for (const { id } of AGENT_DEFINITIONS) expect(sm.get(id)!.state).toBe("MEETING");
  });

  it("meeting_ended resumes the exact task the agent had before the meeting (spec section 16/24)", () => {
    sm.apply(CODEX, { type: "task_assigned", taskId: "t1", title: "Implement Provider Screen", category: "coding" });
    sm.apply(CODEX, { type: "meeting_called" });
    expect(sm.get(CODEX)!.state).toBe("MEETING");

    sm.apply(CODEX, { type: "meeting_ended" });
    const runtime = sm.get(CODEX)!;
    expect(runtime.state).toBe("CODING");
    expect(runtime.taskId).toBe("t1");
    expect(runtime.destination).toBe("frontend_desk");
  });

  it("meeting_ended with no prior task goes IDLE, not stuck in MEETING", () => {
    sm.apply(CODEX, { type: "meeting_called" });
    sm.apply(CODEX, { type: "meeting_ended" });
    expect(sm.get(CODEX)!.state).toBe("IDLE");
  });

  it("a short rate limit sends the agent to the sofa (RESTING), a long one to bed (SLEEPING) -- spec section 20/22/23", () => {
    sm.sleepThresholdMs = 5 * 60_000;
    sm.apply(CODEX, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    sm.apply(CODEX, { type: "rate_limited", cooldownMs: 60_000, provider: "codex_cli" });
    expect(sm.get(CODEX)!.state).toBe("RESTING");
    expect(sm.get(CODEX)!.destination).toMatch(/^lounge_sofa_0/);

    sm.apply(CLAUDE, { type: "task_assigned", taskId: "t2", title: "Y", category: "coding" });
    sm.apply(CLAUDE, { type: "rate_limited", cooldownMs: 10 * 60_000, provider: "claude_code_cli" });
    expect(sm.get(CLAUDE)!.state).toBe("SLEEPING");
    expect(sm.get(CLAUDE)!.destination).toMatch(/^recovery_bed_0/);
  });

  it("provider_recovered wakes the agent and resumes their saved task at their own desk (spec section 24)", () => {
    sm.apply(CLAUDE, { type: "task_assigned", taskId: "t2", title: "Build ProviderManager", category: "coding" });
    sm.apply(CLAUDE, { type: "rate_limited", cooldownMs: 10 * 60_000 });
    expect(sm.get(CLAUDE)!.state).toBe("SLEEPING");

    sm.apply(CLAUDE, { type: "provider_recovered" });
    const runtime = sm.get(CLAUDE)!;
    expect(runtime.state).toBe("CODING");
    expect(runtime.taskId).toBe("t2");
    expect(runtime.destination).toBe("backend_desk");
  });

  it("never assigns two agents the same bed or the same sofa seat -- only 2 of each exist (spec section 40)", () => {
    sm.apply(CEO, { type: "rate_limited", cooldownMs: 10 * 60_000 });
    sm.apply(DESIGNER, { type: "rate_limited", cooldownMs: 10 * 60_000 });
    const bed1 = sm.get(CEO)!.destination;
    const bed2 = sm.get(DESIGNER)!.destination;
    expect(bed1).not.toBe(bed2);

    // A third agent needing a bed while both are occupied still gets a
    // real (non-crashing) resolution, just without a bed of its own.
    sm.apply(CODEX, { type: "rate_limited", cooldownMs: 10 * 60_000 });
    expect(sm.get(CODEX)!.state).toBe("SLEEPING");
    expect(sm.get(CODEX)!.destination).toBe("recovery_room");
  });

  it("error_occurred stops work without moving the agent away from their desk (spec section 26)", () => {
    sm.apply(CODEX, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    sm.apply(CODEX, { type: "error_occurred", message: "Falha real" });
    const runtime = sm.get(CODEX)!;
    expect(runtime.state).toBe("ERROR");
    expect(runtime.destination).toBe("frontend_desk"); // stayed at the desk
    expect(runtime.detail).toBe("Falha real");
  });

  it("waiting_on_dependency stops the agent without discarding its task, and dependency_resolved resumes it", () => {
    sm.apply(CODEX, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    sm.apply(CODEX, { type: "waiting_on_dependency" });
    expect(sm.get(CODEX)!.state).toBe("WAITING");

    sm.apply(CODEX, { type: "dependency_resolved" });
    expect(sm.get(CODEX)!.state).toBe("CODING");
  });

  it("task_completed celebrates then settles back to IDLE on its own (spec section 28)", () => {
    vi.useFakeTimers();
    try {
      sm.apply(CODEX, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
      sm.apply(CODEX, { type: "task_completed" });
      expect(sm.get(CODEX)!.state).toBe("COMPLETED");

      vi.advanceTimersByTime(3000);
      expect(sm.get(CODEX)!.state).toBe("IDLE");
      expect(sm.get(CODEX)!.taskId).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("reset sends every agent back to their own desk, IDLE, with no task (Reset Office debug control)", () => {
    sm.apply(CODEX, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    sm.apply(CODEX, { type: "reset" });
    const runtime = sm.get(CODEX)!;
    expect(runtime.state).toBe("IDLE");
    expect(runtime.taskId).toBeNull();
    expect(runtime.destination).toBe("frontend_desk");
  });

  it("notifies listeners on every transition with the resolved state and destination", () => {
    const events: string[] = [];
    sm.onChange((agentId, runtime) => events.push(`${agentId}:${runtime.state}`));
    sm.apply(CODEX, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    expect(events).toContain("agent_codex:CODING");
  });
});
