import { describe, expect, it, afterEach } from "vitest";
import { OfficeDomainAdapter } from "@/game/agents/OfficeDomainAdapter";
import { agentStateMachine } from "@/game/agents/AgentStateMachine";
import { officeRosterStore } from "@/game/agents/officeRosterStore";
import type { OfficeAgentModel } from "@/game/office-domain/types";

function model(overrides: Partial<OfficeAgentModel> & { agentId: string }): OfficeAgentModel {
  return {
    name: "Atlas", role: "Architect", projectId: "proj_a", projectName: "AgentMash",
    teamId: null, teamName: null, sessionId: null, state: "AVAILABLE",
    visual: { preset: "codex", textureKey: "codex" },
    ...overrides,
  };
}

describe("OfficeDomainAdapter", () => {
  afterEach(() => {
    // Clear every agent this file may have registered on the shared
    // `agentStateMachine` singleton so tests never leak into each other.
    new OfficeDomainAdapter().sync([], false);
    for (const runtime of agentStateMachine.all()) agentStateMachine.removeAgent(runtime.id);
  });

  it("registers a brand-new real agent and gives it a real desk", () => {
    const adapter = new OfficeDomainAdapter();
    adapter.sync([model({ agentId: "agent_atlas", state: "AVAILABLE" })], false);

    const runtime = agentStateMachine.get("agent_atlas");
    expect(runtime).toBeDefined();
    expect(runtime!.state).toBe("IDLE");
  });

  it("a WORKING agent model results in a real working state, never fabricated task content", () => {
    const adapter = new OfficeDomainAdapter();
    adapter.sync([model({ agentId: "agent_atlas", state: "WORKING", sessionId: "sess_1" })], false);

    const runtime = agentStateMachine.get("agent_atlas")!;
    expect(["CODING", "DESIGNING", "RESEARCHING", "PLANNING"]).toContain(runtime.state);
    expect(runtime.taskId).toBe("sess_1");
  });

  it("removing an agent from the roster forgets it entirely", () => {
    const adapter = new OfficeDomainAdapter();
    adapter.sync([model({ agentId: "agent_atlas" })], false);
    expect(agentStateMachine.get("agent_atlas")).toBeDefined();

    adapter.sync([], false);
    expect(agentStateMachine.get("agent_atlas")).toBeUndefined();
  });

  it("does not re-issue the same transition when nothing changed", () => {
    const adapter = new OfficeDomainAdapter();
    adapter.sync([model({ agentId: "agent_atlas", state: "AVAILABLE" })], false);
    const versionAfterFirst = agentStateMachine.get("agent_atlas")!.version;

    adapter.sync([model({ agentId: "agent_atlas", state: "AVAILABLE" })], false);
    expect(agentStateMachine.get("agent_atlas")!.version).toBe(versionAfterFirst);
  });

  it("publishes the roster (with real project/team names) to officeRosterStore", () => {
    const adapter = new OfficeDomainAdapter();
    const agentModel = model({ agentId: "agent_atlas", projectName: "AgentMash" });
    adapter.sync([agentModel], true);

    const roster = officeRosterStore.get();
    expect(roster.showProjectLabels).toBe(true);
    expect(roster.models).toEqual([agentModel]);
  });
});
