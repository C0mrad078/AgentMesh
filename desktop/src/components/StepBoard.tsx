import { Check, Circle, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PhaseProgress } from "@/stores/executionStore";

const PHASE_ORDER = [
  "intent_analysis",
  "planning",
  "routing",
  "execution",
  "verification",
  "aggregation",
];

const PHASE_LABELS: Record<string, string> = {
  intent_analysis: "Analisando intenção",
  planning: "Criando plano",
  routing: "Selecionando agente",
  execution: "Executando tarefa",
  verification: "Verificando resultado",
  aggregation: "Consolidando",
};

function iconFor(status: string | undefined) {
  switch (status) {
    case "completed":
      return <Check className="size-4 text-success" />;
    case "running":
      return <Loader2 className="size-4 animate-spin text-primary" />;
    case "failed":
    case "cancelled":
      return <X className="size-4 text-destructive" />;
    default:
      return <Circle className="size-3 text-muted-foreground" />;
  }
}

export interface StepBoardProps {
  phases: PhaseProgress[];
}

export function StepBoard({ phases }: StepBoardProps) {
  const byPhase = new Map(phases.map((p) => [p.phase, p]));

  return (
    <ol className="flex flex-col gap-2" data-testid="step-board">
      {PHASE_ORDER.map((phase) => {
        const entry = byPhase.get(phase);
        return (
          <li
            key={phase}
            className={cn(
              "flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm",
              entry?.status === "running" && "border-primary/40 bg-primary/5",
            )}
            data-testid={`step-${phase}`}
            data-status={entry?.status ?? "pending"}
          >
            <span>{PHASE_LABELS[phase]}</span>
            {iconFor(entry?.status)}
          </li>
        );
      })}
    </ol>
  );
}
