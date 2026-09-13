import { forwardRef } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// Phaser needs a real canvas/WebGL context jsdom does not provide -- the
// canvas rendering itself is covered by `OfficeController`/`OfficeScene`
// being exercised against the real Phaser API via typecheck, and by
// manual verification in the running app. This test mocks the mount
// component shallowly to verify the *page* wiring (stats, task board,
// hover/click plumbing) around it. Wrapped in `forwardRef` since the real
// component accepts a camera-control ref.
vi.mock("@/components/PhaserOffice", () => ({
  PhaserOffice: forwardRef(function MockPhaserOffice(
    { onClickAgent, onInteractiveObjectClick }: {
      onClickAgent: (id: string) => void;
      onInteractiveObjectClick: (objectId: string) => void;
    },
    _ref,
  ) {
    return (
      <>
        <button onClick={() => onClickAgent("agent_1")}>mock-phaser-canvas</button>
        <button onClick={() => onInteractiveObjectClick("task_board")}>mock-task-board-object</button>
      </>
    );
  }),
}));

import { OfficePage } from "@/pages/OfficePage";
import { useOfficeStore } from "@/stores/officeStore";
import { useUiStore } from "@/stores/uiStore";
import type { VirtualAgent } from "@/office/types";

function makeVirtualAgent(overrides: Partial<VirtualAgent> = {}): VirtualAgent {
  return {
    id: "agent_1", name: "Agent One", role: "Dev", provider: "openai", model: "gpt",
    homeRoom: "backend_desk", state: "WORKING", currentTaskId: "task_1", currentStepId: "estep_1",
    currentExecutionId: "exec_1", destination: "backend_desk", statusDetail: "Implementing feature",
    progress: null, lastActivityAt: null, retryAt: null,
    ...overrides,
  };
}

describe("OfficePage", () => {
  it("shows real roster stats derived from the office store", () => {
    useOfficeStore.setState({
      agents: {
        agent_1: makeVirtualAgent(),
        agent_2: makeVirtualAgent({ id: "agent_2", state: "OFFLINE" }),
      },
      meetings: [], steps: [], loaded: true, error: null,
    });

    render(<OfficePage />);

    expect(screen.getByText("1 agentes online")).toBeInTheDocument();
    expect(screen.getByText("1 trabalhando")).toBeInTheDocument();
  });

  it("shows a real error message when the office failed to load", () => {
    useOfficeStore.setState({ agents: {}, meetings: [], steps: [], loaded: true, error: "bridge unavailable" });

    render(<OfficePage />);

    expect(screen.getByText(/bridge unavailable/)).toBeInTheDocument();
  });

  it("opens the agent detail panel when the canvas reports a click", async () => {
    useOfficeStore.setState({
      agents: { agent_1: makeVirtualAgent() }, meetings: [], steps: [], loaded: true, error: null,
    });

    render(<OfficePage />);
    await userEvent.click(screen.getByText("mock-phaser-canvas"));

    expect(await screen.findByText("Agent One")).toBeInTheDocument();
  });

  it("shows the empty-state message on the task board with no active steps", () => {
    useOfficeStore.setState({ agents: {}, meetings: [], steps: [], loaded: true, error: null });

    render(<OfficePage />);

    expect(screen.getByText(/Nenhuma tarefa em andamento/)).toBeInTheDocument();
  });

  it("clicking the in-canvas Task Board object navigates to the real Tasks page, never a fake panel", async () => {
    useUiStore.setState({ activePage: "office" });
    useOfficeStore.setState({ agents: {}, meetings: [], steps: [], loaded: true, error: null });

    render(<OfficePage />);
    await userEvent.click(screen.getByText("mock-task-board-object"));

    expect(useUiStore.getState().activePage).toBe("workspace");
  });
});
