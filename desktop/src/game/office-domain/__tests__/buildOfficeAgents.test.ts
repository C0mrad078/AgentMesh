import { describe, expect, it } from "vitest";
import { buildOfficeAgents } from "@/game/office-domain/buildOfficeAgents";
import type { Agent, Project, Session, Team } from "@/types";

function project(id: string, name: string): Project {
  return { id, name, description: "", workspace_path: null, status: "active", config: {}, created_at: "now", updated_at: "now" };
}

function agent(overrides: Partial<Agent> & { id: string; name: string }): Agent {
  return {
    description: "", provider: "mock", model: "", system_prompt: "", capabilities: [], tools: [],
    permissions: { can_read_files: true, can_write_files: false, can_run_git: false, can_run_terminal: false, max_tokens_per_call: null },
    config: {}, active: true, role: "", avatar: null, status: "idle",
    preferred_backend: null, fallback_backend: null, memory_profile: {},
    project_id: null, visual_profile: {}, team_ids: [],
    ...overrides,
  };
}

function team(id: string, name: string, project_id: string | null, agent_ids: string[]): Team {
  return { id, name, project_id, description: "", created_at: "now", updated_at: "now", agent_ids };
}

function session(overrides: Partial<Session> & { id: string; agent_id: string; project_id: string }): Session {
  return {
    provider_id: "provider_claude", backend_type: "subscription", account_id: null, task_id: null,
    worktree_id: null, external_session_id: null, status: "working", started_at: "now",
    updated_at: "now", finished_at: null, metadata: {}, created_at: "now",
    ...overrides,
  };
}

describe("buildOfficeAgents", () => {
  // AgentMash V2, Phase 4's own mandated "TESTE CRÍTICO" scenario.
  it("Project A / Project B / All Projects filtering is real, not static", () => {
    const projectA = project("proj_a", "Project A");
    const projectB = project("proj_b", "Project B");
    const agentA = agent({ id: "agent_a", name: "Agent A", project_id: "proj_a" });
    const agentB = agent({ id: "agent_b", name: "Agent B", project_id: "proj_a" });
    const agentC = agent({ id: "agent_c", name: "Agent C", project_id: "proj_b" });
    const agentD = agent({ id: "agent_d", name: "Agent D", project_id: "proj_b" });
    const agents = [agentA, agentB, agentC, agentD];

    const forA = buildOfficeAgents({
      agents, projects: [projectA, projectB], teams: [], sessions: [],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    expect(forA.map((m) => m.agentId).sort()).toEqual(["agent_a", "agent_b"]);

    const forB = buildOfficeAgents({
      agents, projects: [projectA, projectB], teams: [], sessions: [],
      viewMode: "project", selectedProjectId: "proj_b",
    });
    expect(forB.map((m) => m.agentId).sort()).toEqual(["agent_c", "agent_d"]);

    const all = buildOfficeAgents({
      agents, projects: [projectA, projectB], teams: [], sessions: [],
      viewMode: "all", selectedProjectId: null,
    });
    expect(all.map((m) => m.agentId).sort()).toEqual(["agent_a", "agent_b", "agent_c", "agent_d"]);
  });

  it("an agent with no project assignment never appears, in any view mode", () => {
    const unassigned = agent({ id: "agent_x", name: "X", project_id: null });
    const forProject = buildOfficeAgents({
      agents: [unassigned], projects: [], teams: [], sessions: [],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    const forAll = buildOfficeAgents({
      agents: [unassigned], projects: [], teams: [], sessions: [],
      viewMode: "all", selectedProjectId: null,
    });
    expect(forProject).toEqual([]);
    expect(forAll).toEqual([]);
  });

  it("resolves real project and team names, not ids", () => {
    const projectA = project("proj_a", "AgentMash");
    const core = team("team_core", "Core", "proj_a", ["agent_a"]);
    const atlas = agent({ id: "agent_a", name: "Atlas", role: "Architect", project_id: "proj_a", team_ids: ["team_core"] });

    const [model] = buildOfficeAgents({
      agents: [atlas], projects: [projectA], teams: [core], sessions: [],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    expect(model.projectName).toBe("AgentMash");
    expect(model.teamName).toBe("Core");
    expect(model.role).toBe("Architect");
  });

  it("an agent with no active session is AVAILABLE, never fabricated as WORKING", () => {
    const atlas = agent({ id: "agent_a", name: "Atlas", project_id: "proj_a" });
    const [model] = buildOfficeAgents({
      agents: [atlas], projects: [], teams: [], sessions: [],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    expect(model.state).toBe("AVAILABLE");
    expect(model.sessionId).toBeNull();
  });

  it("a disabled agent is OFFLINE even with no session data", () => {
    const disabled = agent({ id: "agent_a", name: "Atlas", project_id: "proj_a", active: false });
    const [model] = buildOfficeAgents({
      agents: [disabled], projects: [], teams: [], sessions: [],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    expect(model.state).toBe("OFFLINE");
  });

  it("a real active session drives WORKING/WAITING state, never invented", () => {
    const atlas = agent({ id: "agent_a", name: "Atlas", project_id: "proj_a" });
    const workingSession = session({ id: "sess_1", agent_id: "agent_a", project_id: "proj_a", status: "working" });

    const [working] = buildOfficeAgents({
      agents: [atlas], projects: [], teams: [], sessions: [workingSession],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    expect(working.state).toBe("WORKING");
    expect(working.sessionId).toBe("sess_1");

    const waitingSession = session({ id: "sess_2", agent_id: "agent_a", project_id: "proj_a", status: "waiting" });
    const [waiting] = buildOfficeAgents({
      agents: [atlas], projects: [], teams: [], sessions: [waitingSession],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    expect(waiting.state).toBe("WAITING");
  });

  it("a terminal (completed) session never counts as active", () => {
    const atlas = agent({ id: "agent_a", name: "Atlas", project_id: "proj_a" });
    const doneSession = session({ id: "sess_1", agent_id: "agent_a", project_id: "proj_a", status: "completed" });
    const [model] = buildOfficeAgents({
      agents: [atlas], projects: [], teams: [], sessions: [doneSession],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    expect(model.state).toBe("AVAILABLE");
    expect(model.sessionId).toBeNull();
  });

  it("resolves a deterministic visual preset from the agent's real profile", () => {
    const atlas = agent({ id: "agent_a", name: "Atlas", project_id: "proj_a", visual_profile: { preset: "codex" } });
    const [model] = buildOfficeAgents({
      agents: [atlas], projects: [], teams: [], sessions: [],
      viewMode: "project", selectedProjectId: "proj_a",
    });
    expect(model.visual.preset).toBe("codex");
  });
});
