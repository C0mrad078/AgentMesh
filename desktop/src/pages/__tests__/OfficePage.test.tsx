import { forwardRef, useImperativeHandle } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PhaserOfficeHandle } from "@/components/PhaserOffice";
import type { AgentInspectInfo, OfficeSummary } from "@/game/scenes/OfficeScene";

const codexInfo: AgentInspectInfo = {
  id: "agent_codex", name: "Codex", roleLabel: "Frontend Developer", state: "CODING",
  taskTitle: "Implement Provider Screen", provider: "codex_cli", progress: 0.5,
  detail: "Implement Provider Screen", room: "Frontend Room", fallbackFrom: null,
};

// Phaser needs a real canvas/WebGL context jsdom does not provide -- the
// canvas rendering itself is covered by game-system unit tests and by
// manual verification in the running app. This test mocks the mount
// component shallowly to verify the *page* wiring (stats, hover/click,
// Task Board navigation, Developer Mode debug panel).
vi.mock("@/components/PhaserOffice", () => ({
  PhaserOffice: forwardRef(function MockPhaserOffice(
    { onClickAgent, onTaskBoardClick, onSummaryChange }: {
      onClickAgent: (id: string) => void;
      onTaskBoardClick: () => void;
      onSummaryChange: (s: OfficeSummary) => void;
    },
    ref: React.Ref<PhaserOfficeHandle>,
  ) {
    useImperativeHandle(ref, () => ({
      zoomIn: vi.fn(), zoomOut: vi.fn(), fit: vi.fn(), reset: vi.fn(),
      followAgent: vi.fn(), stopFollow: vi.fn(), toggleDebug: vi.fn(),
      inspect: (id: string) => (id === "agent_codex" ? codexInfo : null),
      listAgents: () => [codexInfo],
    }));
    return (
      <>
        <button onClick={() => onClickAgent("agent_codex")}>mock-click-codex</button>
        <button onClick={() => onTaskBoardClick()}>mock-task-board</button>
        <button onClick={() => onSummaryChange({ working: 1, meeting: 0, resting: 0, sleeping: 0, waiting: 0, error: 0, idle: 3 })}>
          mock-summary
        </button>
      </>
    );
  }),
}));

vi.mock("@/game/simulation/OfficeSimulationService", () => ({
  officeSimulationService: {
    startWorkday: vi.fn(), startPlanningMeeting: vi.fn(), endMeeting: vi.fn(),
    rateLimitShort: vi.fn(), rateLimitLong: vi.fn(), recover: vi.fn(),
    sendToTesting: vi.fn(), triggerError: vi.fn(), completeTask: vi.fn(), resetOffice: vi.fn(),
  },
}));

import { OfficePage } from "@/pages/OfficePage";
import { useUiStore } from "@/stores/uiStore";
import { officeSimulationService } from "@/game/simulation/OfficeSimulationService";

describe("OfficePage", () => {
  it("shows real roster stats derived from the state machine summary, never a fabricated count", async () => {
    render(<OfficePage />);
    expect(screen.getByText("0 trabalhando")).toBeInTheDocument();

    await userEvent.click(screen.getByText("mock-summary"));
    expect(screen.getByText("1 trabalhando")).toBeInTheDocument();
  });

  it("opens the read-only agent inspector when the canvas reports a click", async () => {
    render(<OfficePage />);
    await userEvent.click(screen.getByText("mock-click-codex"));

    expect(await screen.findByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Implement Provider Screen")).toBeInTheDocument();
  });

  it("clicking the in-world Task Board navigates to the real Tasks page", async () => {
    useUiStore.setState({ activePage: "office" });
    render(<OfficePage />);

    await userEvent.click(screen.getByText("mock-task-board"));

    expect(useUiStore.getState().activePage).toBe("workspace");
  });

  it("Developer Mode is hidden by default and its debug buttons route to OfficeSimulationService", async () => {
    render(<OfficePage />);
    expect(screen.queryByText("Start Workday")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Alternar Developer Mode" }));
    expect(screen.getByText("Start Workday")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Start Workday"));
    expect(officeSimulationService.startWorkday).toHaveBeenCalled();

    await userEvent.click(screen.getByText("Rate Limit Codex"));
    expect(officeSimulationService.rateLimitShort).toHaveBeenCalledWith("agent_codex", "codex_cli");

    await userEvent.click(screen.getByText("Long Cooldown Claude"));
    expect(officeSimulationService.rateLimitLong).toHaveBeenCalledWith("agent_claude_code", "claude_code_cli");

    await userEvent.click(screen.getByText("Reset Office"));
    expect(officeSimulationService.resetOffice).toHaveBeenCalled();
  });
});
