import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  agentsApi: { list: vi.fn() },
  providersApi: { health: vi.fn() },
  executionsApi: { steps: vi.fn() },
}));

import { agentsApi, executionsApi, providersApi } from "@/services/api";
import { useOfficeStore } from "@/stores/officeStore";
import type { Agent } from "@/types";

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "agent_1", name: "Agent One", description: "", provider: "openai", model: "gpt",
    system_prompt: "", capabilities: [{ name: "coding", description: "" }], tools: [],
    permissions: { can_read_files: true, can_write_files: true, can_run_git: true, can_run_terminal: true, max_tokens_per_call: null },
    config: {}, active: true,
    ...overrides,
  };
}

describe("useOfficeStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOfficeStore.setState({ agents: {}, meetings: [], steps: [], loaded: false, error: null });
  });

  it("derives agent states from real API responses when there is no active execution", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([makeAgent()]);
    vi.mocked(providersApi.health).mockResolvedValue([]);

    await useOfficeStore.getState().refresh({ activeExecutionId: null, activeTask: null });

    const state = useOfficeStore.getState();
    expect(state.loaded).toBe(true);
    expect(state.error).toBeNull();
    expect(state.agents["agent_1"].state).toBe("IDLE");
    expect(executionsApi.steps).not.toHaveBeenCalled();
  });

  it("fetches real steps only when an execution is active", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([makeAgent()]);
    vi.mocked(providersApi.health).mockResolvedValue([]);
    vi.mocked(executionsApi.steps).mockResolvedValue([]);

    await useOfficeStore.getState().refresh({ activeExecutionId: "exec_1", activeTask: null });

    expect(executionsApi.steps).toHaveBeenCalledWith("exec_1");
  });

  it("sets an error and still marks loaded when a real API call fails", async () => {
    vi.mocked(agentsApi.list).mockRejectedValue(new Error("network down"));

    await useOfficeStore.getState().refresh({ activeExecutionId: null, activeTask: null });

    const state = useOfficeStore.getState();
    expect(state.loaded).toBe(true);
    expect(state.error).toBe("network down");
  });
});
