import { describe, expect, it } from "vitest";
import { deriveOfficeSnapshot } from "@/office/stateMachine";
import type { Agent, ExecutionStep, ProviderHealthRecord, Task } from "@/types";

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "agent_codex_developer",
    name: "OpenAI Developer",
    description: "",
    provider: "openai",
    model: "gpt-5.1-codex",
    system_prompt: "",
    capabilities: [{ name: "coding", description: "" }],
    tools: [],
    permissions: { can_read_files: true, can_write_files: true, can_run_git: true, can_run_terminal: true, max_tokens_per_call: null },
    config: {},
    active: true,
    role: "",
    avatar: null,
    status: "idle",
    preferred_backend: null,
    fallback_backend: null,
    memory_profile: {},
    ...overrides,
  };
}

function makeStep(overrides: Partial<ExecutionStep> = {}): ExecutionStep {
  return {
    id: "estep_1",
    execution_id: "exec_1",
    step_index: 1,
    name: "Implement feature",
    kind: "work",
    agent_id: "agent_codex_developer",
    provider: "openai",
    status: "running",
    input: { category: "coding" },
    output: null,
    error: null,
    attempt: 1,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task_1",
    project_id: "proj_1",
    conversation_id: null,
    title: "Do the thing",
    description: "",
    mode: "automatic",
    status: "running" as Task["status"],
    input: {},
    result: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

describe("deriveOfficeSnapshot", () => {
  it("an agent with no steps in the execution is IDLE, never fabricated activity", () => {
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent()], steps: [], providerHealth: [], activeTask: null,
    });
    expect(agents["agent_codex_developer"].state).toBe("IDLE");
    expect(agents["agent_codex_developer"].statusDetail).toBeNull();
  });

  it("a disabled agent is OFFLINE regardless of any step data", () => {
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent({ active: false })],
      steps: [makeStep()],
      providerHealth: [],
      activeTask: makeTask(),
    });
    expect(agents["agent_codex_developer"].state).toBe("OFFLINE");
  });

  it("a running coding step puts the agent in WORKING, heading to its desk", () => {
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent()], steps: [makeStep()], providerHealth: [], activeTask: makeTask(),
    });
    const agent = agents["agent_codex_developer"];
    expect(agent.state).toBe("WORKING");
    expect(agent.destination).toBe("frontend_desk"); // codex-family -> frontend desk convention
    expect(agent.statusDetail).toBe("Implement feature");
  });

  it("a running step whose provider is unhealthy overrides WORKING with RATE_LIMITED -> Lounge", () => {
    const health: ProviderHealthRecord[] = [
      { provider: "openai", status: "rate_limited", last_error: "429", consecutive_failures: 1, retry_after_seconds: null },
    ];
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent()], steps: [makeStep()], providerHealth: health, activeTask: makeTask(),
    });
    const agent = agents["agent_codex_developer"];
    expect(agent.state).toBe("RATE_LIMITED");
    expect(agent.destination).toBe("lounge");
  });

  it("a healthy provider does not trigger RATE_LIMITED", () => {
    const health: ProviderHealthRecord[] = [
      { provider: "openai", status: "online", last_error: null, consecutive_failures: 0, retry_after_seconds: null },
    ];
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent()], steps: [makeStep()], providerHealth: health, activeTask: makeTask(),
    });
    expect(agents["agent_codex_developer"].state).toBe("WORKING");
  });

  it("a pending step is WAITING, not WORKING", () => {
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent()], steps: [makeStep({ status: "pending" })], providerHealth: [], activeTask: makeTask(),
    });
    expect(agents["agent_codex_developer"].state).toBe("WAITING");
  });

  it("a failed step is ERROR with the real error message, not invented text", () => {
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent()],
      steps: [makeStep({ status: "failed", error: { message: "Timeout exceeded" } })],
      providerHealth: [],
      activeTask: makeTask(),
    });
    expect(agents["agent_codex_developer"].state).toBe("ERROR");
    expect(agents["agent_codex_developer"].statusDetail).toBe("Timeout exceeded");
  });

  it("a completed step is COMPLETED", () => {
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent()], steps: [makeStep({ status: "completed" })], providerHealth: [], activeTask: makeTask(),
    });
    expect(agents["agent_codex_developer"].state).toBe("COMPLETED");
  });

  it("a testing-category running step routes to the Testing Lab", () => {
    const { agents } = deriveOfficeSnapshot({
      agents: [makeAgent({ id: "agent_codex_tester", capabilities: [{ name: "testing", description: "" }] })],
      steps: [makeStep({ agent_id: "agent_codex_tester", input: { category: "testing" } })],
      providerHealth: [],
      activeTask: makeTask(),
    });
    expect(agents["agent_codex_tester"].state).toBe("TESTING");
    expect(agents["agent_codex_tester"].destination).toBe("testing_lab");
  });

  it("two agents running concurrently under a debate task are put into a real MEETING", () => {
    const agents = [
      makeAgent({ id: "agent_claude_architect", capabilities: [{ name: "architecture", description: "" }] }),
      makeAgent({ id: "agent_codex_developer" }),
    ];
    const steps = [
      makeStep({ id: "s1", agent_id: "agent_claude_architect", provider: "anthropic" }),
      makeStep({ id: "s2", agent_id: "agent_codex_developer", provider: "openai" }),
    ];
    const task = makeTask({ mode: "debate" });
    const { agents: derived, meetings } = deriveOfficeSnapshot({
      agents, steps, providerHealth: [], activeTask: task,
    });
    expect(derived["agent_claude_architect"].state).toBe("MEETING");
    expect(derived["agent_codex_developer"].state).toBe("MEETING");
    expect(meetings).toHaveLength(1);
    expect(meetings[0].participantAgentIds.sort()).toEqual(
      ["agent_claude_architect", "agent_codex_developer"].sort(),
    );
  });

  it("assigns each meeting participant a distinct seat, never the same tile", () => {
    const agents = [
      makeAgent({ id: "agent_claude_architect", capabilities: [{ name: "architecture", description: "" }] }),
      makeAgent({ id: "agent_codex_developer" }),
      makeAgent({ id: "agent_gemini_analyst", capabilities: [{ name: "analysis", description: "" }] }),
    ];
    const steps = [
      makeStep({ id: "s1", agent_id: "agent_claude_architect", provider: "anthropic" }),
      makeStep({ id: "s2", agent_id: "agent_codex_developer", provider: "openai" }),
      makeStep({ id: "s3", agent_id: "agent_gemini_analyst", provider: "gemini" }),
    ];
    const { agents: derived } = deriveOfficeSnapshot({
      agents, steps, providerHealth: [], activeTask: makeTask({ mode: "consensus" }),
    });

    const destinations = [
      derived["agent_claude_architect"].destination,
      derived["agent_codex_developer"].destination,
      derived["agent_gemini_analyst"].destination,
    ];
    expect(new Set(destinations).size).toBe(3); // every seat is distinct
    for (const d of destinations) {
      expect(d).toMatch(/^meeting_seat_0/);
    }
  });

  it("a single running agent under a debate task is not treated as a meeting", () => {
    const { meetings } = deriveOfficeSnapshot({
      agents: [makeAgent()], steps: [makeStep()], providerHealth: [], activeTask: makeTask({ mode: "debate" }),
    });
    expect(meetings).toHaveLength(0);
  });

  it("an automatic-mode task with two running agents is not a meeting", () => {
    const agents = [
      makeAgent({ id: "agent_claude_architect", capabilities: [{ name: "architecture", description: "" }] }),
      makeAgent({ id: "agent_codex_developer" }),
    ];
    const steps = [
      makeStep({ id: "s1", agent_id: "agent_claude_architect", provider: "anthropic" }),
      makeStep({ id: "s2", agent_id: "agent_codex_developer", provider: "openai" }),
    ];
    const { meetings } = deriveOfficeSnapshot({
      agents, steps, providerHealth: [], activeTask: makeTask({ mode: "automatic" }),
    });
    expect(meetings).toHaveLength(0);
  });
});
