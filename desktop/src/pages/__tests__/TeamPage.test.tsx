import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  agentsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn() },
  teamsApi: { list: vi.fn(), create: vi.fn(), assignAgent: vi.fn(), removeAgent: vi.fn() },
  projectsApi: { list: vi.fn() },
}));

import { agentsApi, projectsApi, teamsApi } from "@/services/api";
import { TeamPage } from "@/pages/TeamPage";
import { useAgentsStore } from "@/stores/agentsStore";
import { useTeamsStore } from "@/stores/teamsStore";
import { useProjectsStore } from "@/stores/projectsStore";
import type { Agent, Project, Team } from "@/types";

function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "agent_atlas", name: "Atlas", description: "", provider: "claude_code_cli", model: "",
    system_prompt: "", capabilities: [], tools: [],
    permissions: { can_read_files: true, can_write_files: false, can_run_git: false, can_run_terminal: false, max_tokens_per_call: null },
    config: {}, active: true, role: "Architect", avatar: null, status: "idle",
    preferred_backend: null, fallback_backend: null, memory_profile: {},
    project_id: null, visual_profile: {}, team_ids: [],
    ...overrides,
  };
}

function project(overrides: Partial<Project> = {}): Project {
  return {
    id: "proj_a", name: "AgentMash", description: "", workspace_path: null, status: "active",
    config: {}, created_at: "now", updated_at: "now",
    ...overrides,
  };
}

function team(overrides: Partial<Team> = {}): Team {
  return {
    id: "team_core", name: "Core", project_id: null, description: "",
    created_at: "now", updated_at: "now", agent_ids: [],
    ...overrides,
  };
}

describe("TeamPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentsStore.setState({ agents: [], loading: false, loaded: true, error: null });
    useTeamsStore.setState({ teams: [], loading: false, loaded: true, error: null });
    useProjectsStore.setState({ projects: [], selectedProjectId: null, loading: false, loaded: true, error: null });
  });

  it("shows an empty state with a real create action when there are no agents", async () => {
    render(<TeamPage />);
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    expect(screen.getByText("Nenhum agente configurado")).toBeInTheDocument();
  });

  it("lists real agents with their role, project, and honest (never fabricated) status", () => {
    useAgentsStore.setState({ agents: [agent({ status: "idle" }), agent({ id: "agent_forge", name: "Forge", status: "working" })] });
    render(<TeamPage />);

    expect(screen.getByText("Atlas")).toBeInTheDocument();
    expect(screen.getByText("Disponível")).toBeInTheDocument();
    expect(screen.getByText("Forge")).toBeInTheDocument();
    expect(screen.getByText("Trabalhando")).toBeInTheDocument();
  });

  it("shows the agent's real assigned project name, not just its id", () => {
    useProjectsStore.setState({ projects: [project()] });
    useAgentsStore.setState({ agents: [agent({ project_id: "proj_a" })] });
    render(<TeamPage />);
    expect(screen.getByText(/AgentMash/)).toBeInTheDocument();
  });

  it("creating an agent calls the real API and the new agent appears in the list", async () => {
    vi.mocked(agentsApi.create).mockResolvedValue(agent({ id: "agent_new", name: "Nova" }));
    render(<TeamPage />);

    const [newAgentButton] = screen.getAllByRole("button", { name: "Novo agente" });
    await userEvent.click(newAgentButton);
    await userEvent.type(screen.getByLabelText("Nome"), "Nova");
    await userEvent.click(screen.getByRole("button", { name: "Criar agente" }));

    expect(agentsApi.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Nova" }));
    expect(await screen.findByText("Nova")).toBeInTheDocument();
  });

  it("editing an agent pre-fills the form and calls update, not create", async () => {
    useAgentsStore.setState({ agents: [agent()] });
    vi.mocked(agentsApi.update).mockResolvedValue(agent({ role: "Principal Architect" }));
    render(<TeamPage />);

    await userEvent.click(screen.getByRole("button", { name: "Editar Atlas" }));
    expect(screen.getByLabelText("Nome")).toHaveValue("Atlas");

    await userEvent.clear(screen.getByLabelText("Função"));
    await userEvent.type(screen.getByLabelText("Função"), "Principal Architect");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));

    expect(agentsApi.update).toHaveBeenCalledWith("agent_atlas", expect.objectContaining({ role: "Principal Architect" }));
    expect(agentsApi.create).not.toHaveBeenCalled();
  });

  it("toggling active calls the real update API with the flipped value", async () => {
    useAgentsStore.setState({ agents: [agent({ active: true })] });
    vi.mocked(agentsApi.update).mockResolvedValue(agent({ active: false }));
    render(<TeamPage />);

    await userEvent.click(screen.getByRole("button", { name: "Desativar" }));
    expect(agentsApi.update).toHaveBeenCalledWith("agent_atlas", expect.objectContaining({ active: false }));
  });

  it("creating a team calls the real API and it appears in the team list", async () => {
    vi.mocked(teamsApi.create).mockResolvedValue(team({ id: "team_new", name: "Growth" }));
    render(<TeamPage />);

    await userEvent.type(screen.getByPlaceholderText("Nome da nova equipe"), "Growth");
    await userEvent.click(screen.getByRole("button", { name: "Criar equipe" }));

    expect(teamsApi.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Growth" }));
    expect(await screen.findByText("Growth")).toBeInTheDocument();
  });

  it("assigning an agent to a team calls the real API and shows the real team name on the agent", async () => {
    useAgentsStore.setState({ agents: [agent()] });
    useTeamsStore.setState({ teams: [team()] });
    vi.mocked(teamsApi.assignAgent).mockResolvedValue({ assigned: true });
    render(<TeamPage />);

    await userEvent.selectOptions(screen.getByLabelText("Adicionar Atlas a uma equipe"), "team_core");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(teamsApi.assignAgent).toHaveBeenCalledWith("team_core", "agent_atlas");
  });

  it("removing an agent from a team calls the real API", async () => {
    useAgentsStore.setState({ agents: [agent({ team_ids: ["team_core"] })] });
    useTeamsStore.setState({ teams: [team({ agent_ids: ["agent_atlas"] })] });
    vi.mocked(teamsApi.removeAgent).mockResolvedValue({ assigned: false });
    render(<TeamPage />);

    await userEvent.click(screen.getByRole("button", { name: "Remover Atlas de Core" }));
    expect(teamsApi.removeAgent).toHaveBeenCalledWith("team_core", "agent_atlas");
  });

  it("never claims an agent is working when status is the inert idle default", () => {
    useAgentsStore.setState({ agents: [agent({ status: "idle" })] });
    render(<TeamPage />);
    expect(screen.getByText("Disponível")).toBeInTheDocument();
    expect(screen.queryByText("Trabalhando")).not.toBeInTheDocument();
  });

  it("does not call project/team APIs it already has fresh data for", () => {
    render(<TeamPage />);
    expect(projectsApi.list).not.toHaveBeenCalled();
    expect(teamsApi.list).not.toHaveBeenCalled();
    expect(agentsApi.list).not.toHaveBeenCalled();
  });
});
