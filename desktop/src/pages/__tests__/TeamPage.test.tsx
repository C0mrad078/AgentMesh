import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  agentsApi: { list: vi.fn() },
}));

import { agentsApi } from "@/services/api";
import { TeamPage } from "@/pages/TeamPage";
import type { Agent } from "@/types";

function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "agent_atlas",
    name: "Atlas",
    description: "",
    provider: "claude_code_cli",
    model: "",
    system_prompt: "",
    capabilities: [],
    tools: [],
    permissions: {
      can_read_files: true, can_write_files: false, can_run_git: false, can_run_terminal: false,
      max_tokens_per_call: null,
    },
    config: {},
    active: true,
    role: "Architect",
    avatar: null,
    status: "idle",
    preferred_backend: null,
    fallback_backend: null,
    memory_profile: {},
    ...overrides,
  };
}

describe("TeamPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an empty state when there are no agents", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([]);
    render(<TeamPage />);
    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
  });

  it("lists real agents with their role", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([agent()]);
    render(<TeamPage />);
    expect(await screen.findByText("Atlas")).toBeInTheDocument();
    expect(screen.getByText("Architect")).toBeInTheDocument();
  });

  it("never claims an agent is working when status is the inert idle default", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([agent({ status: "idle" })]);
    render(<TeamPage />);
    expect(await screen.findByText("Disponível")).toBeInTheDocument();
    expect(screen.queryByText("Trabalhando")).not.toBeInTheDocument();
  });

  it("reflects a real working status when the backend reports one", async () => {
    vi.mocked(agentsApi.list).mockResolvedValue([agent({ status: "working" })]);
    render(<TeamPage />);
    expect(await screen.findByText("Trabalhando")).toBeInTheDocument();
  });
});
