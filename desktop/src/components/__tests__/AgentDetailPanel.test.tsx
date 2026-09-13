import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentDetailPanel } from "@/components/AgentDetailPanel";
import { useOfficeStore } from "@/stores/officeStore";
import type { VirtualAgent } from "@/office/types";
import type { ExecutionStep } from "@/types";

function makeVirtualAgent(overrides: Partial<VirtualAgent> = {}): VirtualAgent {
  return {
    id: "agent_1", name: "Agent One", role: "Dev", provider: "openai", model: "gpt-5.1-codex",
    homeRoom: "backend_desk", state: "ERROR", currentTaskId: "task_1", currentStepId: "estep_1",
    currentExecutionId: "exec_1", destination: null, statusDetail: "Erro real", progress: null,
    lastActivityAt: "2026-01-01T00:00:00Z", retryAt: null,
    ...overrides,
  };
}

function makeStep(overrides: Partial<ExecutionStep> = {}): ExecutionStep {
  return {
    id: "estep_1", execution_id: "exec_1", step_index: 1, name: "Implement feature", kind: "work",
    agent_id: "agent_1", provider: "openai", status: "failed", input: {}, output: null,
    error: { message: "Timeout exceeded" }, attempt: 2, started_at: "2026-01-01T00:00:00Z", completed_at: null,
    ...overrides,
  };
}

describe("AgentDetailPanel", () => {
  it("shows real step error detail, never fabricated", () => {
    useOfficeStore.setState({
      agents: { agent_1: makeVirtualAgent() }, meetings: [], steps: [makeStep()], loaded: true, error: null,
    });

    render(<AgentDetailPanel agentId="agent_1" onClose={vi.fn()} />);

    expect(screen.getByText("Agent One")).toBeInTheDocument();
    expect(screen.getByText("Timeout exceeded")).toBeInTheDocument();
    expect(screen.getByText(/Tentativa 2/)).toBeInTheDocument();
  });

  it("shows the idle message when there is no current step", () => {
    useOfficeStore.setState({
      agents: { agent_1: makeVirtualAgent({ currentStepId: null, state: "IDLE" }) },
      meetings: [], steps: [], loaded: true, error: null,
    });

    render(<AgentDetailPanel agentId="agent_1" onClose={vi.fn()} />);

    expect(screen.getByText(/está ocioso na mesa dele/)).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", async () => {
    const onClose = vi.fn();
    useOfficeStore.setState({
      agents: { agent_1: makeVirtualAgent() }, meetings: [], steps: [makeStep()], loaded: true, error: null,
    });

    render(<AgentDetailPanel agentId="agent_1" onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "Fechar" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing for an unknown agent id", () => {
    useOfficeStore.setState({ agents: {}, meetings: [], steps: [], loaded: true, error: null });

    const { container } = render(<AgentDetailPanel agentId="does_not_exist" onClose={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });
});
