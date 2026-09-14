import { describe, expect, it, beforeEach, vi } from "vitest";
import { AgentStateMachine } from "@/game/agents/AgentStateMachine";
import { workstationSystem, WORKSTATION_CAPACITY } from "@/game/systems/WorkstationSystem";
import { bedSystem } from "@/game/systems/BedSystem";
import { sofaSystem } from "@/game/systems/SofaSystem";
import { meetingRoomSystem } from "@/game/systems/MeetingRoomSystem";

// AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md): desks are a real,
// anonymous pool now (4 of them, `WORKSTATION_CAPACITY`), not one fixed
// desk per fixed character id -- these tests use generic real agent ids
// instead of the old Stage 2/3 fixed 4, and assert desk *pool* behavior
// (deterministic claim order, overflow) rather than a specific agent
// always landing on one specific named desk.
const AGENT_A = "agent_a";
const AGENT_B = "agent_b";
const AGENT_C = "agent_c";
const AGENT_D = "agent_d";
const AGENT_E = "agent_e";
const ALL_TEST_AGENTS = [AGENT_A, AGENT_B, AGENT_C, AGENT_D, AGENT_E];

// The occupancy systems (beds/sofa/meeting seats/desks) are shared
// singletons -- release every agent from all of them between tests so
// state from one test never leaks into the next.
function resetOccupancy() {
  for (const id of ALL_TEST_AGENTS) {
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

  it("a brand-new agent id is created on first use, IDLE with no destination", () => {
    sm.ensureAgent(AGENT_A);
    expect(sm.get(AGENT_A)?.state).toBe("IDLE");
  });

  it("apply() auto-registers an agent id it has never seen before", () => {
    expect(sm.get(AGENT_A)).toBeUndefined();
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    expect(sm.get(AGENT_A)).toBeDefined();
  });

  it("removeAgent forgets the agent and releases whatever spot it held", () => {
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    sm.removeAgent(AGENT_A);
    expect(sm.get(AGENT_A)).toBeUndefined();

    // Its desk is free again for someone else.
    sm.apply(AGENT_B, { type: "task_assigned", taskId: "t2", title: "Y", category: "coding" });
    expect(sm.get(AGENT_B)!.destination).not.toBeNull();
  });

  it("task_assigned claims a real desk from the pool and sits the agent in the right work state", () => {
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "Implement Provider Screen", category: "coding", provider: "codex_cli" });
    const runtime = sm.get(AGENT_A)!;
    expect(runtime.state).toBe("CODING");
    expect(runtime.destination).not.toBeNull();
    expect(runtime.taskTitle).toBe("Implement Provider Screen");
    expect(runtime.provider).toBe("codex_cli");
  });

  it("designer gets DESIGNING, CEO gets PLANNING, from the same event shape", () => {
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t2", title: "Design Agent Settings", category: "designing" });
    expect(sm.get(AGENT_A)!.state).toBe("DESIGNING");
    sm.apply(AGENT_B, { type: "task_assigned", taskId: "t3", title: "Plan sprint", category: "planning" });
    expect(sm.get(AGENT_B)!.state).toBe("PLANNING");
  });

  it("never assigns two agents the same desk -- each gets a distinct one up to capacity", () => {
    for (const id of ALL_TEST_AGENTS.slice(0, WORKSTATION_CAPACITY)) {
      sm.apply(id, { type: "task_assigned", taskId: `t-${id}`, title: "X", category: "coding" });
    }
    const destinations = ALL_TEST_AGENTS.slice(0, WORKSTATION_CAPACITY).map((id) => sm.get(id)!.destination);
    expect(new Set(destinations).size).toBe(WORKSTATION_CAPACITY);
  });

  it("overflow -- a 5th simultaneous agent beyond desk capacity never crashes, goes to the lounge", () => {
    for (const id of ALL_TEST_AGENTS) {
      sm.apply(id, { type: "task_assigned", taskId: `t-${id}`, title: "X", category: "coding" });
    }
    expect(sm.get(AGENT_E)!.state).toBe("CODING"); // still a real work state, not crashed/stuck
    expect(sm.get(AGENT_E)!.destination).toBe("lounge");
  });

  it("meeting_called moves every agent to a distinct real meeting seat (spec section 14/15/39)", () => {
    for (const id of [AGENT_A, AGENT_B, AGENT_C, AGENT_D]) sm.apply(id, { type: "meeting_called" });
    const destinations = [AGENT_A, AGENT_B, AGENT_C, AGENT_D].map((id) => sm.get(id)!.destination);
    expect(new Set(destinations).size).toBe(4); // no two agents share a seat
    for (const d of destinations) expect(d).toMatch(/^meeting_seat_0/);
    for (const id of [AGENT_A, AGENT_B, AGENT_C, AGENT_D]) expect(sm.get(id)!.state).toBe("MEETING");
  });

  it("meeting_ended resumes the exact task the agent had before the meeting (spec section 16/24)", () => {
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "Implement Provider Screen", category: "coding" });
    const deskBeforeMeeting = sm.get(AGENT_A)!.destination;
    sm.apply(AGENT_A, { type: "meeting_called" });
    expect(sm.get(AGENT_A)!.state).toBe("MEETING");

    sm.apply(AGENT_A, { type: "meeting_ended" });
    const runtime = sm.get(AGENT_A)!;
    expect(runtime.state).toBe("CODING");
    expect(runtime.taskId).toBe("t1");
    expect(runtime.destination).toBe(deskBeforeMeeting); // same desk it claimed before, not a different one
  });

  it("meeting_ended with no prior task goes IDLE, not stuck in MEETING", () => {
    sm.apply(AGENT_A, { type: "meeting_called" });
    sm.apply(AGENT_A, { type: "meeting_ended" });
    expect(sm.get(AGENT_A)!.state).toBe("IDLE");
  });

  it("a short rate limit sends the agent to the sofa (RESTING), a long one to bed (SLEEPING) -- spec section 20/22/23", () => {
    sm.sleepThresholdMs = 5 * 60_000;
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    sm.apply(AGENT_A, { type: "rate_limited", cooldownMs: 60_000, provider: "codex_cli" });
    expect(sm.get(AGENT_A)!.state).toBe("RESTING");
    expect(sm.get(AGENT_A)!.destination).toMatch(/^lounge_sofa_0/);

    sm.apply(AGENT_B, { type: "task_assigned", taskId: "t2", title: "Y", category: "coding" });
    sm.apply(AGENT_B, { type: "rate_limited", cooldownMs: 10 * 60_000, provider: "claude_code_cli" });
    expect(sm.get(AGENT_B)!.state).toBe("SLEEPING");
    expect(sm.get(AGENT_B)!.destination).toMatch(/^recovery_bed_0/);
  });

  it("provider_recovered wakes the agent and resumes their saved task at a real desk (spec section 24)", () => {
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t2", title: "Build ProviderManager", category: "coding" });
    sm.apply(AGENT_A, { type: "rate_limited", cooldownMs: 10 * 60_000 });
    expect(sm.get(AGENT_A)!.state).toBe("SLEEPING");

    sm.apply(AGENT_A, { type: "provider_recovered" });
    const runtime = sm.get(AGENT_A)!;
    expect(runtime.state).toBe("CODING");
    expect(runtime.taskId).toBe("t2");
    expect(runtime.destination).not.toBeNull();
  });

  it("never assigns two agents the same bed or the same sofa seat -- only 2 of each exist (spec section 40)", () => {
    sm.apply(AGENT_A, { type: "rate_limited", cooldownMs: 10 * 60_000 });
    sm.apply(AGENT_B, { type: "rate_limited", cooldownMs: 10 * 60_000 });
    const bed1 = sm.get(AGENT_A)!.destination;
    const bed2 = sm.get(AGENT_B)!.destination;
    expect(bed1).not.toBe(bed2);

    // A third agent needing a bed while both are occupied still gets a
    // real (non-crashing) resolution, just without a bed of its own.
    sm.apply(AGENT_C, { type: "rate_limited", cooldownMs: 10 * 60_000 });
    expect(sm.get(AGENT_C)!.state).toBe("SLEEPING");
    expect(sm.get(AGENT_C)!.destination).toBe("recovery_room");
  });

  it("error_occurred stops work without moving the agent away from their desk (spec section 26)", () => {
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    const desk = sm.get(AGENT_A)!.destination;
    sm.apply(AGENT_A, { type: "error_occurred", message: "Falha real" });
    const runtime = sm.get(AGENT_A)!;
    expect(runtime.state).toBe("ERROR");
    expect(runtime.destination).toBe(desk); // stayed at the desk
    expect(runtime.detail).toBe("Falha real");
  });

  it("waiting_on_dependency stops the agent without discarding its task, and dependency_resolved resumes it", () => {
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    sm.apply(AGENT_A, { type: "waiting_on_dependency" });
    expect(sm.get(AGENT_A)!.state).toBe("WAITING");

    sm.apply(AGENT_A, { type: "dependency_resolved" });
    expect(sm.get(AGENT_A)!.state).toBe("CODING");
  });

  it("task_completed celebrates then settles back to IDLE on its own (spec section 28)", () => {
    vi.useFakeTimers();
    try {
      sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
      sm.apply(AGENT_A, { type: "task_completed" });
      expect(sm.get(AGENT_A)!.state).toBe("COMPLETED");

      vi.advanceTimersByTime(3000);
      expect(sm.get(AGENT_A)!.state).toBe("IDLE");
      expect(sm.get(AGENT_A)!.taskId).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("reset sends the agent back to a real desk, IDLE, with no task (Reset Office debug control)", () => {
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    sm.apply(AGENT_A, { type: "reset" });
    const runtime = sm.get(AGENT_A)!;
    expect(runtime.state).toBe("IDLE");
    expect(runtime.taskId).toBeNull();
    expect(runtime.destination).not.toBeNull();
  });

  it("notifies listeners on every transition with the resolved state and destination", () => {
    const events: string[] = [];
    sm.onChange((agentId, runtime) => events.push(`${agentId}:${runtime.state}`));
    sm.apply(AGENT_A, { type: "task_assigned", taskId: "t1", title: "X", category: "coding" });
    expect(events).toContain(`${AGENT_A}:CODING`);
  });
});
