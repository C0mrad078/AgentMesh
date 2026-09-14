import { useEffect, useState } from "react";
import { Loader2, Users } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/utils";
import { agentsApi } from "@/services/api";
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
 * AgentMash V2 (docs/agentmash-v2-migration.md): replaces the V1
 * `AgentsPage` card grid entirely -- the brief explicitly forbids reusing
 * that UI for "Team" ("Não utilizar antiga UI de agents. Criar do zero").
 * A plain roster list instead, matching the brief's own reference
 * ("Atlas / Architect / ● Working"). `status` is real, persisted data
 * (Refactor V2 Phase 1) but nothing computes it live yet (Presence Engine
 * is a later phase) -- every agent honestly reads "Disponível" (the
 * inert IDLE default) until real sessions start driving it, never a
 * fabricated "Working".
 */
export function TeamPage() {
  const [agents, setAgents] = useState<Agent[] | null>(null);

  useEffect(() => {
    void agentsApi.list().then(setAgents);
  }, []);

  if (agents === null) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <EmptyState icon={<Users className="size-8 text-muted-foreground" />} title="Nenhum agente configurado" />
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-1">
      <h2 className="mb-2 text-sm font-semibold">Equipe</h2>
      {agents.map((agent) => (
        <div
          key={agent.id}
          data-testid="team-member"
          className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{agent.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {agent.role || agent.description || agent.provider}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
            <span className={cn("size-2 rounded-full", STATUS_DOT[agent.status])} />
            {STATUS_LABEL[agent.status]}
          </div>
        </div>
      ))}
    </div>
  );
}
