import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentDetailPanel } from "@/components/AgentDetailPanel";
import type { AgentInspectInfo } from "@/game/scenes/OfficeScene";

function makeInfo(overrides: Partial<AgentInspectInfo> = {}): AgentInspectInfo {
  return {
    id: "agent_codex", name: "Codex", roleLabel: "Frontend Developer", state: "CODING",
    taskTitle: "Implement Provider Screen", provider: "codex_cli", progress: 0.68,
    detail: "Implement Provider Screen", room: "Frontend Room", fallbackFrom: null,
    ...overrides,
  };
}

describe("AgentDetailPanel", () => {
  it("shows the agent's real name, role, task, provider, room, and progress", () => {
    render(<AgentDetailPanel agent={makeInfo()} onClose={vi.fn()} />);

    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Frontend Developer")).toBeInTheDocument();
    expect(screen.getByText("Implement Provider Screen")).toBeInTheDocument();
    expect(screen.getByText("codex_cli")).toBeInTheDocument();
    expect(screen.getByText("Frontend Room")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();
  });

  it("shows 'Fallback from: X' when the task was picked up from another real agent", () => {
    render(<AgentDetailPanel agent={makeInfo({ fallbackFrom: "Codex" })} onClose={vi.fn()} />);
    expect(screen.getByText("Fallback from: Codex")).toBeInTheDocument();
  });

  it("shows no fallback note when the task was assigned directly", () => {
    render(<AgentDetailPanel agent={makeInfo()} onClose={vi.fn()} />);
    expect(screen.queryByText(/Fallback from:/)).not.toBeInTheDocument();
  });

  it("marks ERROR and BLOCKED states with the destructive badge", () => {
    render(<AgentDetailPanel agent={makeInfo({ state: "ERROR" })} onClose={vi.fn()} />);
    expect(screen.getByText("Erro")).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", async () => {
    const onClose = vi.fn();
    render(<AgentDetailPanel agent={makeInfo()} onClose={onClose} />);

    await userEvent.click(screen.getByRole("button", { name: "Fechar" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("calls onFollow when the follow button is clicked", async () => {
    const onFollow = vi.fn();
    render(<AgentDetailPanel agent={makeInfo()} onClose={vi.fn()} onFollow={onFollow} />);

    await userEvent.click(screen.getByRole("button", { name: "Seguir agente" }));

    expect(onFollow).toHaveBeenCalled();
  });
});
