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
import { useProjectsStore } from "@/stores/projectsStore";
import { useOfficeSelectionStore } from "@/stores/officeSelectionStore";
import { officeSimulationService } from "@/game/simulation/OfficeSimulationService";

describe("OfficePage", () => {
  it("the project filter lists real projects and switching to 'All Projects' updates real selection state", async () => {
    useProjectsStore.setState({
      projects: [
        { id: "proj_a", name: "AgentMash", description: "", workspace_path: null, status: "active", config: {}, created_at: "now", updated_at: "now" },
        { id: "proj_b", name: "NerdVerso", description: "", workspace_path: null, status: "active", config: {}, created_at: "now", updated_at: "now" },
      ],
      selectedProjectId: "proj_a", loaded: true, loading: false, error: null,
    });
    useOfficeSelectionStore.setState({ viewMode: "project" });

    render(<OfficePage />);
    const select = screen.getByLabelText("Filtro de projeto do Office") as HTMLSelectElement;
    expect(select.value).toBe("proj_a");

    await userEvent.selectOptions(select, "all");
    expect(useOfficeSelectionStore.getState().viewMode).toBe("all");

    await userEvent.selectOptions(select, "proj_b");
    expect(useOfficeSelectionStore.getState().viewMode).toBe("project");
    expect(useProjectsStore.getState().selectedProjectId).toBe("proj_b");
  });

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

    await userEvent.click(screen.getByText("Reset Office"));
    expect(officeSimulationService.resetOffice).toHaveBeenCalled();
  });

  it("per-agent debug actions are disabled with no selection, and target the real selected agent once one is picked", async () => {
    render(<OfficePage />);
    await userEvent.click(screen.getByRole("button", { name: "Alternar Developer Mode" }));

    // Phase 4: retired the hardcoded "agent_codex"/"agent_claude_code"
    // buttons -- these act on whichever real agent is selected/hovered.
    expect(screen.getByText("Rate Limit (selecionado)")).toBeDisabled();

    await userEvent.click(screen.getByText("mock-click-codex")); // selects the real agent from the click event
    expect(screen.getByText("Rate Limit (selecionado)")).not.toBeDisabled();

    await userEvent.click(screen.getByText("Rate Limit (selecionado)"));
    expect(officeSimulationService.rateLimitShort).toHaveBeenCalledWith("agent_codex");

    await userEvent.click(screen.getByText("Complete Task (selecionado)"));
    expect(officeSimulationService.completeTask).toHaveBeenCalledWith("agent_codex");
  });
});
