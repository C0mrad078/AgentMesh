import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  agentsApi: {
    list: vi.fn(),
  },
}));

import { agentsApi } from "@/services/api";
import { AgentPicker } from "@/components/AgentPicker";
import type { Agent } from "@/types";

function makeAgent(id: string, name: string): Agent {
  return {
    id,
    name,
    description: "",
    provider: "anthropic",
    model: "claude",
    system_prompt: "",
    capabilities: [],
    tools: [],
    permissions: {
      can_read_files: true,
      can_write_files: false,
      can_run_git: false,
      can_run_terminal: false,
      max_tokens_per_call: null,
    },
    config: {},
    active: true,
  };
}

describe("AgentPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing for automatic mode", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([makeAgent("agent_a", "Agent A")]);
    const { container } = render(
      <AgentPicker mode="automatic" selected={[]} onChange={() => {}} />,
    );
    await waitFor(() => expect(agentsApi.list).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("single-selects an agent in manual mode", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([
      makeAgent("agent_a", "Agent A"),
      makeAgent("agent_b", "Agent B"),
    ]);
    const onChange = vi.fn();
    render(<AgentPicker mode="manual" selected={[]} onChange={onChange} />);

    const button = await screen.findByRole("button", { name: "Agent A" });
    await userEvent.click(button);

    expect(onChange).toHaveBeenCalledWith(["agent_a"]);
  });

  it("toggles multi-selection in pipeline mode and shows order numbers", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([
      makeAgent("agent_a", "Agent A"),
      makeAgent("agent_b", "Agent B"),
    ]);
    const onChange = vi.fn();
    const { rerender } = render(
      <AgentPicker mode="pipeline" selected={["agent_a"]} onChange={onChange} />,
    );

    expect(await screen.findByText("1.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Agent B/ }));
    expect(onChange).toHaveBeenCalledWith(["agent_a", "agent_b"]);

    await userEvent.click(screen.getByRole("button", { name: /Agent A/ }));
    expect(onChange).toHaveBeenLastCalledWith([]);

    rerender(<AgentPicker mode="pipeline" selected={["agent_a"]} onChange={onChange} />);
    expect(screen.getByText("Limpar seleção")).toBeInTheDocument();
  });

  it("filters out inactive agents", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([
      { ...makeAgent("agent_a", "Agent A"), active: false },
      makeAgent("agent_b", "Agent B"),
    ]);
    render(<AgentPicker mode="manual" selected={[]} onChange={() => {}} />);

    await screen.findByRole("button", { name: "Agent B" });
    expect(screen.queryByRole("button", { name: "Agent A" })).not.toBeInTheDocument();
  });
});
