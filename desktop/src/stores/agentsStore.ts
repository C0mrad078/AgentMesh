import { create } from "zustand";
import { agentsApi } from "@/services/api";
import type { Agent, ExecutionBackendType } from "@/types";

export interface AgentCreateInput {
  name: string;
  role?: string;
  description?: string;
  provider?: string;
  preferred_backend?: ExecutionBackendType | null;
  project_id?: string | null;
  visual_profile?: Record<string, string>;
}

export interface AgentUpdateInput {
  name?: string;
  role?: string;
  description?: string;
  provider?: string;
  preferred_backend?: ExecutionBackendType | null;
  project_id?: string | null;
  active?: boolean;
  visual_profile?: Record<string, string>;
}

interface AgentsState {
  agents: Agent[];
  loading: boolean;
  loaded: boolean;
  error: string | null;
  loadAgents: () => Promise<void>;
  createAgent: (input: AgentCreateInput) => Promise<Agent>;
  updateAgent: (agentId: string, input: AgentUpdateInput) => Promise<Agent>;
}

/** AgentMash V2, Phase 4: the single real source of agents for the whole
 * app -- Team page and the Office's domain adapter both read from this,
 * never from a hardcoded/mocked list (docs/agentmash-v2-phase4.md). */
export const useAgentsStore = create<AgentsState>((set, get) => ({
  agents: [],
  loading: false,
  loaded: false,
  error: null,

  loadAgents: async () => {
    set({ loading: true, error: null });
    try {
      const agents = await agentsApi.list();
      set({ agents, loading: false, loaded: true });
    } catch (error) {
      set({ loading: false, error: error instanceof Error ? error.message : String(error) });
    }
  },

  createAgent: async (input) => {
    const agent = await agentsApi.create(input);
    set({ agents: [...get().agents, agent] });
    return agent;
  },

  updateAgent: async (agentId, input) => {
    const agent = await agentsApi.update(agentId, input);
    set({ agents: get().agents.map((a) => (a.id === agentId ? agent : a)) });
    return agent;
  },
}));
