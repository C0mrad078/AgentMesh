import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  tasksApi: {
    create: vi.fn(),
    get: vi.fn(),
    cancel: vi.fn(),
  },
  executionsApi: {
    start: vi.fn(),
    cancel: vi.fn(),
    steps: vi.fn().mockResolvedValue([]),
    usage: vi.fn().mockResolvedValue({
      entries: [],
      total_cost_usd: 0,
      total_input_tokens: 0,
      total_output_tokens: 0,
    }),
  },
  agentsApi: {
    list: vi.fn().mockResolvedValue([]),
  },
}));

import { tasksApi, executionsApi } from "@/services/api";
import { useExecutionStore } from "@/stores/executionStore";

describe("useExecutionStore", () => {
  beforeEach(() => {
    useExecutionStore.setState({
      activeTaskId: null,
      activeExecutionId: null,
      phases: [],
      agentEntries: [],
      costUsd: null,
      task: null,
      submitting: false,
      error: null,
      fallbacks: {},
    });
    vi.clearAllMocks();
  });

  it("submitTask creates a task and starts an execution", async () => {
    vi.mocked(tasksApi.create).mockResolvedValue({
      id: "task_1",
      project_id: "proj_1",
      conversation_id: null,
      title: "Do X",
      description: "",
      mode: "automatic",
      status: "queued",
      input: {},
      result: null,
      created_at: "now",
      updated_at: "now",
      started_at: null,
      completed_at: null,
    });
    vi.mocked(executionsApi.start).mockResolvedValue({ task_id: "task_1", status: "started" });

    await useExecutionStore.getState().submitTask({ projectId: "proj_1", title: "Do X" });

    expect(tasksApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: "proj_1", title: "Do X" }),
    );
    expect(executionsApi.start).toHaveBeenCalledWith("task_1");
    expect(useExecutionStore.getState().activeTaskId).toBe("task_1");
  });

  it("handleProgressEvent ignores events for a different task", () => {
    useExecutionStore.setState({ activeTaskId: "task_1" });
    useExecutionStore.getState().handleProgressEvent({
      execution_id: "exec_1",
      task_id: "task_other",
      phase: "planning",
      phase_label: "Criando plano",
      status: "running",
      detail: null,
    });
    expect(useExecutionStore.getState().phases).toHaveLength(0);
  });

  it("handleProgressEvent upserts phases for the active task", () => {
    useExecutionStore.setState({ activeTaskId: "task_1" });
    const store = useExecutionStore.getState();

    store.handleProgressEvent({
      execution_id: "exec_1",
      task_id: "task_1",
      phase: "planning",
      phase_label: "Criando plano",
      status: "running",
      detail: null,
    });
    store.handleProgressEvent({
      execution_id: "exec_1",
      task_id: "task_1",
      phase: "planning",
      phase_label: "Criando plano",
      status: "completed",
      detail: null,
    });

    const { phases, activeExecutionId } = useExecutionStore.getState();
    expect(phases).toHaveLength(1);
    expect(phases[0].status).toBe("completed");
    expect(activeExecutionId).toBe("exec_1");
  });

  it("cancelActive prefers cancelling the execution when one is known", async () => {
    useExecutionStore.setState({ activeTaskId: "task_1", activeExecutionId: "exec_1" });
    vi.mocked(executionsApi.cancel).mockResolvedValue({ execution_id: "exec_1", cancel_requested: true });

    await useExecutionStore.getState().cancelActive();

    expect(executionsApi.cancel).toHaveBeenCalledWith("exec_1");
    expect(tasksApi.cancel).not.toHaveBeenCalled();
  });

  it("handleOrchestrationEvent records a real fallback.used event, keyed by the agent that picked up the work", () => {
    useExecutionStore.setState({ activeExecutionId: "exec_1" });
    useExecutionStore.getState().handleOrchestrationEvent("fallback.used", {
      execution_id: "exec_1", from_agent_id: "agent_codex_cli_developer",
      to_agent_id: "agent_claude_code_architect", reason: "provider_unavailable",
    });

    const { fallbacks } = useExecutionStore.getState();
    expect(fallbacks["agent_claude_code_architect"]).toEqual({
      fromAgentId: "agent_codex_cli_developer", toAgentId: "agent_claude_code_architect",
      reason: "provider_unavailable",
    });
  });

  it("ignores a fallback.used event for a different execution", () => {
    useExecutionStore.setState({ activeExecutionId: "exec_1" });
    useExecutionStore.getState().handleOrchestrationEvent("fallback.used", {
      execution_id: "exec_other", from_agent_id: "agent_codex_cli_developer", to_agent_id: "agent_claude_code_architect",
    });

    expect(useExecutionStore.getState().fallbacks).toEqual({});
  });

  it("cancelActive surfaces a rejected task cancellation as a store error instead of throwing", async () => {
    useExecutionStore.setState({ activeTaskId: "task_1", activeExecutionId: null });
    vi.mocked(tasksApi.cancel).mockRejectedValue(new Error("Task 'task_1' is 'running', not 'queued'."));

    await expect(useExecutionStore.getState().cancelActive()).resolves.toBeUndefined();

    expect(useExecutionStore.getState().error).toContain("running");
  });
});
