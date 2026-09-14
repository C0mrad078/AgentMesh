import { create } from "zustand";
import { teamsApi } from "@/services/api";
import type { Team } from "@/types";

interface TeamsState {
  teams: Team[];
  loading: boolean;
  loaded: boolean;
  error: string | null;
  loadTeams: () => Promise<void>;
  createTeam: (input: { name: string; project_id?: string | null; description?: string }) => Promise<Team>;
  assignAgent: (teamId: string, agentId: string) => Promise<void>;
  removeAgent: (teamId: string, agentId: string) => Promise<void>;
}

/** AgentMash V2, Phase 4: Team membership is real and persisted (`core.teams`)
 * -- this store is the frontend's only source for it, never a fixture. */
export const useTeamsStore = create<TeamsState>((set, get) => ({
  teams: [],
  loading: false,
  loaded: false,
  error: null,

  loadTeams: async () => {
    set({ loading: true, error: null });
    try {
      const teams = await teamsApi.list();
      set({ teams, loading: false, loaded: true });
    } catch (error) {
      set({ loading: false, error: error instanceof Error ? error.message : String(error) });
    }
  },

  createTeam: async (input) => {
    const team = await teamsApi.create(input);
    set({ teams: [...get().teams, team] });
    return team;
  },

  assignAgent: async (teamId, agentId) => {
    await teamsApi.assignAgent(teamId, agentId);
    set({
      teams: get().teams.map((t) =>
        t.id === teamId && !t.agent_ids.includes(agentId)
          ? { ...t, agent_ids: [...t.agent_ids, agentId] }
          : t,
      ),
    });
  },

  removeAgent: async (teamId, agentId) => {
    await teamsApi.removeAgent(teamId, agentId);
    set({
      teams: get().teams.map((t) =>
        t.id === teamId ? { ...t, agent_ids: t.agent_ids.filter((id) => id !== agentId) } : t,
      ),
    });
  },
}));
