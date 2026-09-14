import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { RealOfficeAdapter } from "@/game/agents/RealOfficeAdapter";
import { agentStateMachine } from "@/game/agents/AgentStateMachine";
import type { Agent, ExecutionStep, ProviderHealthRecord, Task } from "@/types";

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "agent_codex_cli_developer", name: "Codex CLI Developer", description: "", provider: "codex_cli",
    model: "default", capabilities: [{ name: "coding", description: "" }], active: true,
    ...overrides,
  } as Agent;
}

function makeStep(overrides: Partial<ExecutionStep> = {}): ExecutionStep {
  return {
    id: "estep_1", execution_id: "exec_1", step_index: 0, name: "Implement Provider Screen", kind: "work",
    agent_id: "agent_codex_cli_developer", provider: "codex_cli", status: "running",
    input: { category: "coding" }, output: null, error: null, attempt: 1,
    started_at: "2026-01-01T00:00:00Z", completed_at: null,
    ...overrides,
  };
}

function health(overrides: Partial<ProviderHealthRecord> = {}): ProviderHealthRecord {
  return { provider: "codex_cli", status: "online", last_error: null, consecutive_failures: 0, retry_after_seconds: null, ...overrides };
}

describe("RealOfficeAdapter", () => {
  let apply: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    apply = vi.spyOn(agentStateMachine, "apply");
  });
  afterEach(() => {
    apply.mockRestore();
  });

  it("maps a real CLI agent's WORKING step to task_assigned on the correct visual role", () => {
    const adapter = new RealOfficeAdapter();
    adapter.sync({
      agents: [makeAgent()], steps: [makeStep()], providerHealth: [health()], activeTask: null,
    });

    expect(apply).toHaveBeenCalledWith("agent_codex", expect.objectContaining({
      type: "task_assigned", category: "coding", provider: "codex_cli", title: "Implement Provider Screen",
    }));
  });

  it("never re-issues the same event when nothing real changed", () => {
    const adapter = new RealOfficeAdapter();
    const input = { agents: [makeAgent()], steps: [makeStep()], providerHealth: [health()], activeTask: null };
    adapter.sync(input);
    apply.mockClear();
    adapter.sync(input);
    expect(apply).not.toHaveBeenCalled();
  });

  it("meeting_called then meeting_ended when a real debate step starts and finishes", () => {
    const adapter = new RealOfficeAdapter();
    const task: Task = { id: "t1", project_id: "p1", title: "X", mode: "debate" } as Task;

    // Before the debate starts, both agents are just plainly WORKING
    // (no `activeTask`, so `deriveOfficeSnapshot` can't see a debate).
    adapter.sync({
      agents: [makeAgent(), makeAgent({ id: "agent_claude_code_architect", provider: "claude_code_cli" })],
      steps: [
        makeStep({ id: "s1", agent_id: "agent_codex_cli_developer" }),
        makeStep({ id: "s2", agent_id: "agent_claude_code_architect", provider: "claude_code_cli" }),
      ],
      providerHealth: [health()], activeTask: null,
    });
    apply.mockClear();

    // Both steps now report a running debate on the same task -- the real
    // signal `deriveOfficeSnapshot` uses to derive MEETING.
    adapter.sync({
      agents: [makeAgent(), makeAgent({ id: "agent_claude_code_architect", provider: "claude_code_cli" })],
      steps: [
        makeStep({ id: "s1", agent_id: "agent_codex_cli_developer" }),
        makeStep({ id: "s2", agent_id: "agent_claude_code_architect", provider: "claude_code_cli" }),
      ],
      providerHealth: [health()], activeTask: task,
    });

    expect(apply).toHaveBeenCalledWith("agent_codex", { type: "meeting_called" });
    expect(apply).toHaveBeenCalledWith("agent_claude_code", { type: "meeting_called" });
  });

  it("rate_limited carries the real retryAfter converted to milliseconds", () => {
    const adapter = new RealOfficeAdapter();
    adapter.sync({
      agents: [makeAgent()],
      steps: [makeStep({ status: "running" })],
      providerHealth: [health({ status: "rate_limited", retry_after_seconds: 30 })],
      activeTask: null,
    });

    expect(apply).toHaveBeenCalledWith("agent_codex", {
      type: "rate_limited", cooldownMs: 30_000, provider: "codex_cli",
    });
  });

  it("an unknown-duration rate limit is treated as short, never invented as long (spec section 36)", () => {
    const adapter = new RealOfficeAdapter();
    adapter.sync({
      agents: [makeAgent()],
      steps: [makeStep({ status: "running" })],
      providerHealth: [health({ status: "rate_limited", retry_after_seconds: null })],
      activeTask: null,
    });

    const call = apply.mock.calls.find((c) => c[0] === "agent_codex")!;
    expect(call[1]).toMatchObject({ type: "rate_limited" });
    expect((call[1] as { cooldownMs: number }).cooldownMs).toBeLessThan(5 * 60_000);
  });

  it("provider_recovered resumes after a rate limit, not a fresh task_assigned", () => {
    const adapter = new RealOfficeAdapter();
    adapter.sync({
      agents: [makeAgent()],
      steps: [makeStep({ status: "running" })],
      providerHealth: [health({ status: "rate_limited", retry_after_seconds: 5 })],
      activeTask: null,
    });
    apply.mockClear();

    adapter.sync({
      agents: [makeAgent()], steps: [makeStep({ status: "running" })], providerHealth: [health()], activeTask: null,
    });

    expect(apply).toHaveBeenCalledWith("agent_codex", { type: "provider_recovered" });
  });

  it("maps a failed step to error_occurred with the real error detail", () => {
    const adapter = new RealOfficeAdapter();
    adapter.sync({
      agents: [makeAgent()],
      steps: [makeStep({ status: "failed", error: { message: "Timeout" } })],
      providerHealth: [health()], activeTask: null,
    });

    expect(apply).toHaveBeenCalledWith("agent_codex", { type: "error_occurred", message: "Timeout" });
  });

  it("when the owning real agent goes idle, resets that visual role instead of leaving it stuck", () => {
    const adapter = new RealOfficeAdapter();
    adapter.sync({
      agents: [makeAgent()], steps: [makeStep({ status: "running" })], providerHealth: [health()], activeTask: null,
    });
    apply.mockClear();

    adapter.sync({ agents: [makeAgent()], steps: [], providerHealth: [health()], activeTask: null });

    expect(apply).toHaveBeenCalledWith("agent_codex", { type: "reset" });
  });

  it("two real agents mapped to the same visual role: the more urgent real state wins", () => {
    const adapter = new RealOfficeAdapter();
    // agent_reviewer and agent_claude_code_architect both map to agent_claude_code.
    adapter.sync({
      agents: [
        makeAgent({ id: "agent_reviewer", provider: "mock", capabilities: [{ name: "analysis", description: "" }] }),
        makeAgent({ id: "agent_claude_code_architect", provider: "claude_code_cli" }),
      ],
      steps: [
        makeStep({ id: "s1", agent_id: "agent_reviewer", provider: "mock", status: "failed", error: { message: "boom" } }),
        makeStep({ id: "s2", agent_id: "agent_claude_code_architect", provider: "claude_code_cli", status: "running" }),
      ],
      providerHealth: [health(), health({ provider: "mock" })], activeTask: null,
    });

    // ERROR outranks WORKING -- the failed reviewer's state is the one
    // shown for the shared "Claude Code" visual role this frame.
    expect(apply).toHaveBeenCalledWith("agent_claude_code", expect.objectContaining({ type: "error_occurred" }));
  });
});
