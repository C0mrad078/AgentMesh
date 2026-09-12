import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  executionsApi: {
    list: vi.fn(),
    steps: vi.fn(),
    usage: vi.fn(),
    routing: vi.fn(),
  },
}));

import { executionsApi } from "@/services/api";
import { ExecutionsPage } from "@/pages/ExecutionsPage";
import { useProjectsStore } from "@/stores/projectsStore";
import type { Execution, ExecutionStep, RoutingDecisionRecord } from "@/types";

const PROJECT = {
  id: "proj_1",
  name: "Demo",
  description: "",
  workspace_path: null,
  status: "active" as const,
  config: {},
  created_at: "now",
  updated_at: "now",
};

const EXECUTION: Execution = {
  id: "exec_1",
  task_id: "task_1",
  project_id: "proj_1",
  status: "completed",
  plan: {},
  current_step_index: 2,
  attempt: 1,
  error: null,
  started_at: "2026-01-01T00:00:00Z",
  completed_at: "2026-01-01T00:00:05Z",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:05Z",
};

const STEP: ExecutionStep = {
  id: "step_1",
  execution_id: "exec_1",
  step_index: 1,
  name: "Implementar",
  kind: "work",
  agent_id: "agent_claude_architect",
  provider: "anthropic",
  status: "completed",
  input: {},
  output: null,
  error: null,
  attempt: 1,
  started_at: null,
  completed_at: null,
};

const ROUTING: RoutingDecisionRecord = {
  id: "route_1",
  execution_id: "exec_1",
  step_id: "step_1",
  agent_id: "agent_claude_architect",
  provider: "anthropic",
  model: "claude-x",
  score: 0.87,
  reason: "Melhor capacidade para coding disponível.",
  alternatives: [],
  created_at: "now",
};

describe("ExecutionsPage", () => {
  beforeEach(() => {
    useProjectsStore.setState({
      projects: [PROJECT],
      selectedProjectId: "proj_1",
      loaded: true,
      loading: false,
      error: null,
    });
    vi.clearAllMocks();
  });

  it("shows an empty state when there is no execution history", async () => {
    vi.mocked(executionsApi.list).mockResolvedValue([]);
    render(<ExecutionsPage />);
    expect(await screen.findByText("Nenhuma execução ainda")).toBeInTheDocument();
  });

  it("expands a row to show steps, cost, and technical details on demand", async () => {
    vi.mocked(executionsApi.list).mockResolvedValue([EXECUTION]);
    vi.mocked(executionsApi.steps).mockResolvedValue([STEP]);
    vi.mocked(executionsApi.usage).mockResolvedValue({
      entries: [],
      total_cost_usd: 0.0123,
      total_input_tokens: 100,
      total_output_tokens: 50,
    });
    vi.mocked(executionsApi.routing).mockResolvedValue([ROUTING]);

    render(<ExecutionsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByText("exec_1"));
    expect(
      await screen.findByText((_, el) => el?.textContent === "↳ Implementar · anthropic"),
    ).toBeInTheDocument();
    expect(screen.getAllByText((_, el) => el?.textContent === "$0.0123").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Ver detalhes técnicos" }));
    expect(await screen.findByText("Melhor capacidade para coding disponível.")).toBeInTheDocument();
    expect(executionsApi.routing).toHaveBeenCalledWith("exec_1");
  });
});
