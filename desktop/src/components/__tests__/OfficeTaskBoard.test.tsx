import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OfficeTaskBoard } from "@/components/OfficeTaskBoard";
import { useOfficeStore } from "@/stores/officeStore";
import type { ExecutionStep } from "@/types";
import type { VirtualAgent } from "@/office/types";

function makeStep(overrides: Partial<ExecutionStep> = {}): ExecutionStep {
  return {
    id: "estep_1", execution_id: "exec_1", step_index: 1, name: "Implement feature", kind: "work",
    agent_id: "agent_1", provider: "openai", status: "running", input: {}, output: null,
    error: null, attempt: 1, started_at: null, completed_at: null,
    ...overrides,
  };
}

function makeVirtualAgent(overrides: Partial<VirtualAgent> = {}): VirtualAgent {
  return {
    id: "agent_1", name: "Agent One", role: "Dev", provider: "openai", model: "gpt",
    homeRoom: "backend_desk", state: "WORKING", currentTaskId: null, currentStepId: null,
    currentExecutionId: null, destination: null, statusDetail: null, progress: null,
    lastActivityAt: null, retryAt: null,
    ...overrides,
  };
}

describe("OfficeTaskBoard", () => {
  it("does not loop and groups real steps into the correct real-status columns", () => {
    useOfficeStore.setState({
      agents: { agent_1: makeVirtualAgent() },
      meetings: [],
      steps: [
        makeStep({ id: "s1", status: "pending", name: "Plan the fix" }),
        makeStep({ id: "s2", status: "running", name: "Implement the fix" }),
        makeStep({ id: "s3", status: "completed", name: "Write tests" }),
        makeStep({ id: "s4", status: "failed", name: "Deploy" }),
        // A phase step must never appear on the board -- it isn't real
        // agent work, just orchestration bookkeeping.
        makeStep({ id: "s5", kind: "phase", name: "Planejando" }),
      ],
      loaded: true,
      error: null,
    });

    render(<OfficeTaskBoard />);

    expect(screen.getByText("Plan the fix")).toBeInTheDocument();
    expect(screen.getByText("Implement the fix")).toBeInTheDocument();
    expect(screen.getByText("Write tests")).toBeInTheDocument();
    expect(screen.getByText("Deploy")).toBeInTheDocument();
    expect(screen.queryByText("Planejando")).not.toBeInTheDocument();
    expect(screen.getAllByText("Agent One")).toHaveLength(4);
  });
});
