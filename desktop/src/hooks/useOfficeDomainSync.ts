import { useEffect } from "react";
import { buildOfficeAgents } from "@/game/office-domain/buildOfficeAgents";
import { officeDomainAdapter } from "@/game/agents/OfficeDomainAdapter";
import { useAgentsStore } from "@/stores/agentsStore";
import { useOfficeSelectionStore } from "@/stores/officeSelectionStore";
import { useProjectsStore } from "@/stores/projectsStore";
import { useSessionsStore } from "@/stores/sessionsStore";
import { useTeamsStore } from "@/stores/teamsStore";

// No runtime yet produces a push event when a session changes (Phase 5+
// wires that in) -- a light poll is the only way to notice one, mirroring
// the same "não testar a cada segundo" restraint `useBridgeSubscription`'s
// provider-health poll already uses.
const SESSIONS_POLL_MS = 15_000;

/**
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md): the real, default
 * source of the autonomous office's roster -- replaces Stage 3's
 * `useRealOfficeSync` (which drove the office from DAG execution/routing
 * events through a fixed 4-character mapping, both retired this phase).
 * Mounted once near the app root; reacts to real `Agent`/`Team`/`Session`/
 * `Project`/office-selection state and recomputes
 * `buildOfficeAgents()` -> `OfficeDomainAdapter.sync()` whenever any of it
 * changes. Never touches Phaser directly (`OfficeDomainAdapter`/
 * `officeRosterStore` are the only bridge to the scene).
 */
export function useOfficeDomainSync(): void {
  useEffect(() => {
    void useAgentsStore.getState().loadAgents();
    void useTeamsStore.getState().loadTeams();
    void useSessionsStore.getState().loadSessions();
    if (!useProjectsStore.getState().loaded) void useProjectsStore.getState().loadProjects();

    const sync = () => {
      const { agents } = useAgentsStore.getState();
      const { teams } = useTeamsStore.getState();
      const { sessions } = useSessionsStore.getState();
      const { projects, selectedProjectId } = useProjectsStore.getState();
      const { viewMode } = useOfficeSelectionStore.getState();

      const models = buildOfficeAgents({
        agents, projects, teams, sessions, viewMode, selectedProjectId,
      });
      officeDomainAdapter.sync(models, viewMode === "all");
    };

    sync(); // initial snapshot -- also this phase's crash/reload recovery
    const unsubscribers = [
      useAgentsStore.subscribe(sync),
      useTeamsStore.subscribe(sync),
      useSessionsStore.subscribe(sync),
      useProjectsStore.subscribe(sync),
      useOfficeSelectionStore.subscribe(sync),
    ];

    const interval = setInterval(() => void useSessionsStore.getState().loadSessions(), SESSIONS_POLL_MS);

    return () => {
      for (const unsubscribe of unsubscribers) unsubscribe();
      clearInterval(interval);
    };
  }, []);
}
