import { resolveVisualProfile } from "@/game/office-domain/visualProfile";
import type { OfficeAgentModel, OfficePresenceState } from "@/game/office-domain/types";
import { TERMINAL_SESSION_STATUSES, type Agent, type Project, type Session, type Team } from "@/types";

export interface BuildOfficeAgentsInput {
  agents: Agent[];
  projects: Project[];
  teams: Team[];
  sessions: Session[];
  /** "project": only `selectedProjectId`'s agents. "all": every agent
   * that belongs to *some* project (an unassigned agent never appears in
   * the Office, in either mode -- there is nowhere real for it to be). */
  viewMode: "project" | "all";
  selectedProjectId: string | null;
}

function deriveState(agent: Agent, session: Session | null): OfficePresenceState {
  // AgentMash V2, Phase 4 "OFFICE PRESENCE STATE": no runtime exists yet
  // to drive this from real execution -- state comes from the domain
  // alone (a real active session if one exists, else the agent's own
  // persisted `active`/`status`), never fabricated to look busier than
  // it really is.
  if (session) {
    switch (session.status) {
      case "working":
        return "WORKING";
      case "waiting":
      case "paused":
      case "blocked":
        return "WAITING";
      case "failed":
        return "ERROR";
      default:
        return "AVAILABLE";
    }
  }
  if (!agent.active) return "OFFLINE";
  if (agent.status === "offline") return "OFFLINE";
  if (agent.status === "working") return "WORKING"; // honestly reflects a persisted value, even though nothing computes it live yet (see Agent.status docs)
  return "AVAILABLE";
}

/**
 * The one place real `Agent`/`Project`/`Team`/`Session` records become
 * what the Pixel Office renders. Pure and Phaser-free by design (brief
 * "PHASER TESTABILITY") -- every filtering/derivation rule here is
 * covered by `buildOfficeAgents.test.ts` without starting a single Phaser
 * scene.
 */
export function buildOfficeAgents(input: BuildOfficeAgentsInput): OfficeAgentModel[] {
  const projectById = new Map(input.projects.map((p) => [p.id, p]));
  const teamById = new Map(input.teams.map((t) => [t.id, t]));

  const activeSessionByAgent = new Map<string, Session>();
  for (const session of input.sessions) {
    if (TERMINAL_SESSION_STATUSES.includes(session.status)) continue;
    const existing = activeSessionByAgent.get(session.agent_id);
    if (!existing || session.created_at > existing.created_at) {
      activeSessionByAgent.set(session.agent_id, session);
    }
  }

  const scoped = input.agents.filter((agent) => {
    if (!agent.project_id) return false;
    if (input.viewMode === "all") return true;
    return agent.project_id === input.selectedProjectId;
  });

  return scoped.map((agent) => {
    const project = agent.project_id ? (projectById.get(agent.project_id) ?? null) : null;
    const teamId = agent.team_ids[0] ?? null;
    const team = teamId ? (teamById.get(teamId) ?? null) : null;
    const session = activeSessionByAgent.get(agent.id) ?? null;

    return {
      agentId: agent.id,
      name: agent.name,
      role: agent.role || agent.description,
      projectId: agent.project_id,
      projectName: project?.name ?? null,
      teamId,
      teamName: team?.name ?? null,
      sessionId: session?.id ?? null,
      state: deriveState(agent, session),
      visual: resolveVisualProfile(agent.id, agent.visual_profile),
    };
  });
}
