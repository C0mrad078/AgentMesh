import { LocateFixed, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useOfficeStore } from "@/stores/officeStore";
import { roomLabel } from "@/office/map";
import type { VirtualAgent } from "@/office/types";

const STATE_LABEL: Record<VirtualAgent["state"], string> = {
  OFFLINE: "Offline", IDLE: "Ocioso", PLANNING: "Planejando", MOVING: "Em trânsito",
  WORKING: "Trabalhando", TESTING: "Testando", REVIEWING: "Revisando", MEETING: "Em reunião",
  WAITING: "Aguardando", BLOCKED: "Bloqueado", RATE_LIMITED: "Rate limit", RESTING: "Descansando",
  ERROR: "Erro", COMPLETED: "Concluído",
};

interface AgentDetailPanelProps {
  agentId: string;
  onClose: () => void;
  onFollow?: () => void;
  following?: boolean;
}

export function AgentDetailPanel({ agentId, onClose, onFollow, following }: AgentDetailPanelProps) {
  const agent = useOfficeStore((s) => s.agents[agentId]);
  const step = useOfficeStore((s) => s.steps.find((st) => st.id === agent?.currentStepId));

  if (!agent) return null;

  return (
    <div className="flex h-full w-80 flex-col border-l border-border bg-card">
      <div className="flex items-center justify-between border-b border-border p-3">
        <div>
          <p className="text-sm font-semibold">{agent.name}</p>
          <p className="text-xs text-muted-foreground">{roomLabel(agent.homeRoom)}</p>
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

      <ScrollArea className="flex-1">
        <div className="flex flex-col gap-3 p-3 text-sm">
          <div className="flex items-center gap-2">
            <Badge variant={agent.state === "ERROR" ? "destructive" : "secondary"}>
              {STATE_LABEL[agent.state]}
            </Badge>
          </div>

          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">Provider</dt>
            <dd>{agent.provider}</dd>
            <dt className="text-muted-foreground">Model</dt>
            <dd>{agent.model}</dd>
            {agent.currentTaskId && (
              <>
                <dt className="text-muted-foreground">Tarefa</dt>
                <dd className="truncate">{agent.currentTaskId}</dd>
              </>
            )}
            {agent.statusDetail && (
              <>
                <dt className="text-muted-foreground">Atividade</dt>
                <dd>{agent.statusDetail}</dd>
              </>
            )}
            {agent.lastActivityAt && (
              <>
                <dt className="text-muted-foreground">Desde</dt>
                <dd>{new Date(agent.lastActivityAt).toLocaleTimeString()}</dd>
              </>
            )}
          </dl>

          {step && (
            <div className="flex flex-col gap-1.5 border-t border-border pt-3">
              <p className="text-xs font-medium text-muted-foreground">Detalhes do step</p>
              <p className="text-xs">
                Tentativa {step.attempt} &middot; status {step.status}
              </p>
              {step.error && (
                <p className="text-xs text-destructive">
                  {typeof step.error.message === "string" ? step.error.message : JSON.stringify(step.error)}
                </p>
              )}
              {step.output && Object.keys(step.output).length > 0 && (
                <pre className="whitespace-pre-wrap break-words rounded bg-muted p-2 text-[11px]">
                  {JSON.stringify(step.output, null, 2).slice(0, 1000)}
                </pre>
              )}
            </div>
          )}

          {!step && (
            <p className="border-t border-border pt-3 text-xs text-muted-foreground">
              Sem step ativo nesta execução -- este agente está ocioso na mesa dele.
            </p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
