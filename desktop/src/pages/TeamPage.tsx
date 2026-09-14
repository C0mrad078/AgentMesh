import { useEffect, useState } from "react";
import { Loader2, Pencil, Plus, Users } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AgentFormDialog } from "@/components/AgentFormDialog";
import { cn } from "@/lib/utils";
import { useAgentsStore } from "@/stores/agentsStore";
import { useTeamsStore } from "@/stores/teamsStore";
import { useProjectsStore } from "@/stores/projectsStore";
import type { Agent, AgentStatus } from "@/types";

const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: "Disponível",
  working: "Trabalhando",
  offline: "Offline",
};

const STATUS_DOT: Record<AgentStatus, string> = {
  idle: "bg-muted-foreground",
  working: "bg-success",
  offline: "bg-border",
};

/**
 * AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md "TEAM PAGE"): real
 * agent management -- create, edit, assign project, assign team, set
 * role, set visual preset, enable/disable -- all against the real
 * `agentsStore`/`teamsStore` (`core.agents`/`core.teams`), never a
 * dashboard card grid (the brief explicitly forbids reusing the old
 * `AgentsPage` UI for this).
 */
export function TeamPage() {
  const { agents, loaded: agentsLoaded, loadAgents, updateAgent } = useAgentsStore();
  const { teams, loaded: teamsLoaded, loadTeams, createTeam, assignAgent, removeAgent: removeAgentFromTeam } = useTeamsStore();
  const { projects, loadProjects, loaded: projectsLoaded } = useProjectsStore();

  const [formOpen, setFormOpen] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [newTeamName, setNewTeamName] = useState("");
  const [teamPickerByAgent, setTeamPickerByAgent] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!agentsLoaded) void loadAgents();
    if (!teamsLoaded) void loadTeams();
    if (!projectsLoaded) void loadProjects();
  }, [agentsLoaded, teamsLoaded, projectsLoaded, loadAgents, loadTeams, loadProjects]);

  function openCreate() {
    setEditingAgent(null);
    setFormOpen(true);
  }

  function openEdit(agent: Agent) {
    setEditingAgent(agent);
    setFormOpen(true);
  }

  async function handleCreateTeam() {
    if (!newTeamName.trim()) return;
    await createTeam({ name: newTeamName.trim() });
    setNewTeamName("");
  }

  const projectNameById = new Map(projects.map((p) => [p.id, p.name]));
  const teamById = new Map(teams.map((t) => [t.id, t]));

  if (!agentsLoaded && agents.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Equipe</h2>
        <Button size="sm" onClick={openCreate}>
          <Plus className="size-4" /> Novo agente
        </Button>
      </div>

      <div className="flex flex-col gap-2 rounded-md border border-border p-3">
        <p className="text-xs font-medium text-muted-foreground">Equipes</p>
        <div className="flex flex-wrap gap-1.5">
          {teams.map((team) => (
            <Badge key={team.id} variant="outline">
              {team.name}{team.project_id && projectNameById.get(team.project_id) ? ` · ${projectNameById.get(team.project_id)}` : ""}
            </Badge>
          ))}
          {teams.length === 0 && <span className="text-xs text-muted-foreground">Nenhuma equipe ainda.</span>}
        </div>
        <div className="flex gap-2">
          <input
            className="h-8 flex-1 rounded-md border border-input bg-transparent px-2 text-xs"
            placeholder="Nome da nova equipe"
            value={newTeamName}
            onChange={(e) => setNewTeamName(e.target.value)}
          />
          <Button size="sm" variant="outline" className="h-8" onClick={() => void handleCreateTeam()}>
            Criar equipe
          </Button>
        </div>
      </div>

      {agents.length === 0 ? (
        <EmptyState
          icon={<Users className="size-8 text-muted-foreground" />}
          title="Nenhum agente configurado"
          description="Crie o primeiro agente para começar a montar a equipe."
          action={<Button size="sm" onClick={openCreate}><Plus className="size-4" /> Novo agente</Button>}
        />
      ) : (
        <div className="flex flex-col gap-1.5">
          {agents.map((agent) => (
            <div key={agent.id} data-testid="team-member" className="flex flex-col gap-2 rounded-md border border-border p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{agent.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {agent.role || agent.description || agent.provider}
                    {agent.project_id && projectNameById.get(agent.project_id) && ` · ${projectNameById.get(agent.project_id)}`}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className={cn("size-2 rounded-full", STATUS_DOT[agent.status])} />
                    {STATUS_LABEL[agent.status]}
                  </div>
                  <Button size="icon" variant="ghost" className="size-7" aria-label={`Editar ${agent.name}`} onClick={() => openEdit(agent)}>
                    <Pencil className="size-3.5" />
                  </Button>
                  <Button
                    size="sm" variant="outline" className="h-7 text-xs"
                    onClick={() => void updateAgent(agent.id, { active: !agent.active })}
                  >
                    {agent.active ? "Desativar" : "Ativar"}
                  </Button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                {agent.team_ids.map((teamId) => (
                  <Badge key={teamId} variant="secondary" className="gap-1">
                    {teamById.get(teamId)?.name ?? teamId}
                    <button
                      type="button"
                      aria-label={`Remover ${agent.name} de ${teamById.get(teamId)?.name ?? teamId}`}
                      className="ml-0.5 opacity-70 hover:opacity-100"
                      onClick={() => void removeAgentFromTeam(teamId, agent.id)}
                    >
                      ×
                    </button>
                  </Badge>
                ))}
                {teams.length > 0 && (
                  <div className="flex items-center gap-1">
                    <select
                      aria-label={`Adicionar ${agent.name} a uma equipe`}
                      className="h-6 rounded-md border border-input bg-transparent px-1 text-[11px]"
                      value={teamPickerByAgent[agent.id] ?? ""}
                      onChange={(e) => setTeamPickerByAgent((prev) => ({ ...prev, [agent.id]: e.target.value }))}
                    >
                      <option value="">+ equipe</option>
                      {teams.filter((t) => !agent.team_ids.includes(t.id)).map((t) => (
                        <option key={t.id} value={t.id}>{t.name}</option>
                      ))}
                    </select>
                    <Button
                      size="sm" variant="ghost" className="h-6 px-1.5 text-[11px]"
                      disabled={!teamPickerByAgent[agent.id]}
                      onClick={() => {
                        const teamId = teamPickerByAgent[agent.id];
                        if (!teamId) return;
                        void assignAgent(teamId, agent.id);
                        setTeamPickerByAgent((prev) => ({ ...prev, [agent.id]: "" }));
                      }}
                    >
                      Add
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <AgentFormDialog open={formOpen} onOpenChange={setFormOpen} agent={editingAgent} projects={projects} />
    </div>
  );
}
