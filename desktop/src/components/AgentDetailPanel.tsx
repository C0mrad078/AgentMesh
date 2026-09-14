import { LocateFixed, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { AgentInspectInfo } from "@/game/scenes/OfficeScene";

const STATE_LABEL: Record<string, string> = {
  OFFLINE: "Offline", IDLE: "Ocioso", MOVING: "Em trânsito", PLANNING: "Planejando",
  WORKING: "Trabalhando", CODING: "Codando", DESIGNING: "Desenhando", RESEARCHING: "Pesquisando",
  TESTING: "Testando", REVIEWING: "Revisando", MEETING: "Em reunião", WAITING: "Aguardando",
  BLOCKED: "Bloqueado", RATE_LIMITED: "Rate limit", COOLDOWN: "Cooldown", RESTING: "Descansando",
  SLEEPING: "Dormindo", ERROR: "Erro", COMPLETED: "Concluído",
};

const ERROR_STATES = new Set(["ERROR", "BLOCKED"]);

interface AgentDetailPanelProps {
  agent: AgentInspectInfo;
  onClose: () => void;
  onFollow?: () => void;
  following?: boolean;
}

/** Spec section 32/34/35: click opens this read-only inspector -- it
 * never lets the user command the agent, only observe it. */
export function AgentDetailPanel({ agent, onClose, onFollow, following }: AgentDetailPanelProps) {
  return (
    <div className="flex w-72 flex-col rounded-lg border border-border bg-card/95 shadow-xl backdrop-blur">
      <div className="flex items-center justify-between border-b border-border p-3">
        <div>
          <p className="text-sm font-semibold">{agent.name}</p>
          <p className="text-xs text-muted-foreground">{agent.roleLabel}</p>
        </div>
        <div className="flex items-center gap-1">
          {onFollow && (
            <Button
              size="icon"
              variant={following ? "secondary" : "ghost"}
              className="size-7"
              onClick={onFollow}
              aria-label="Seguir agente"
            >
              <LocateFixed className="size-4" />
            </Button>
          )}
          <Button size="icon" variant="ghost" className="size-7" onClick={onClose} aria-label="Fechar">
            <X className="size-4" />
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-2 p-3 text-sm">
        <Badge variant={ERROR_STATES.has(agent.state) ? "destructive" : "secondary"} className="w-fit">
          {STATE_LABEL[agent.state] ?? agent.state}
        </Badge>

        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
          {agent.taskTitle && (
            <>
              <dt className="text-muted-foreground">Tarefa</dt>
              <dd className="truncate">{agent.taskTitle}</dd>
            </>
          )}
          {agent.provider && (
            <>
              <dt className="text-muted-foreground">Provider</dt>
              <dd>{agent.provider}</dd>
            </>
          )}
          {agent.fallbackFrom && (
            <>
              <dt className="text-muted-foreground">Fallback</dt>
              <dd className="truncate" title={`Fallback from: ${agent.fallbackFrom}`}>
                Fallback from: {agent.fallbackFrom}
              </dd>
            </>
          )}
          <dt className="text-muted-foreground">Sala</dt>
          <dd>{agent.room ?? "Corredor"}</dd>
          {agent.progress !== null && (
            <>
              <dt className="text-muted-foreground">Progresso</dt>
              <dd>{Math.round(agent.progress * 100)}%</dd>
            </>
          )}
        </dl>

        {agent.detail && agent.detail !== agent.taskTitle && (
          <p className="border-t border-border pt-2 text-xs text-muted-foreground">{agent.detail}</p>
        )}
      </div>
    </div>
  );
}
