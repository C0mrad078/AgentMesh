import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { agentsApi } from "@/services/api";
import type { Agent, TaskMode } from "@/types";

const HINT_BY_MODE: Partial<Record<TaskMode, string>> = {
  manual: "Escolha o agente que deve executar a tarefa.",
  pipeline: "Escolha os agentes, na ordem em que devem atuar (clique define a ordem).",
  debate: "Escolha os agentes que vão responder de forma independente antes da síntese.",
  consensus: "Escolha os agentes que vão responder de forma independente antes da síntese.",
};

export interface AgentPickerProps {
  mode: TaskMode;
  selected: string[];
  onChange: (ids: string[]) => void;
}

export function AgentPicker({ mode, selected, onChange }: AgentPickerProps) {
  const [agents, setAgents] = useState<Agent[] | null>(null);

  useEffect(() => {
    void agentsApi.list().then(setAgents);
  }, []);

  if (mode === "automatic") return null;
  if (agents === null) {
    return <Loader2 className="size-4 animate-spin text-muted-foreground" />;
  }

  const multi = mode !== "manual";

  function toggle(agentId: string) {
    if (!multi) {
      onChange([agentId]);
      return;
    }
    onChange(
      selected.includes(agentId) ? selected.filter((id) => id !== agentId) : [...selected, agentId],
    );
  }

  return (
    <div className="flex flex-col gap-2" data-testid="agent-picker">
      <p className="text-xs text-muted-foreground">{HINT_BY_MODE[mode]}</p>
      <div className="flex flex-wrap gap-2">
        {agents
          .filter((agent) => agent.active)
          .map((agent) => {
            const index = selected.indexOf(agent.id);
            const isSelected = index >= 0;
            return (
              <button
                key={agent.id}
                type="button"
                onClick={() => toggle(agent.id)}
                aria-pressed={isSelected}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors",
                  isSelected
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:bg-accent",
                )}
              >
                {mode === "pipeline" && isSelected && (
                  <span className="mr-1 font-semibold">{index + 1}.</span>
                )}
                {agent.name}
              </button>
            );
          })}
      </div>
      {multi && selected.length > 0 && (
        <Button variant="ghost" size="sm" className="h-6 self-start px-2 text-[11px]" onClick={() => onChange([])}>
          Limpar seleção
        </Button>
      )}
    </div>
  );
}
