import { useMemo } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useOfficeStore } from "@/stores/officeStore";
import type { ExecutionStep, StepStatus } from "@/types";

/**
 * Reflects the real DAG steps of the active execution -- never a
 * separate, invented data source (spec section 21). Columns are exactly
 * the statuses `ExecutionStep.status` actually has; there is no backend
 * concept of a "Review" column distinct from "running", so this
 * deliberately does not invent one (see VIRTUAL_OFFICE.md).
 */
const COLUMNS: { status: StepStatus[]; label: string }[] = [
  { status: ["pending"], label: "Backlog" },
  { status: ["running"], label: "Em progresso" },
  { status: ["completed"], label: "Concluído" },
  { status: ["failed", "cancelled", "skipped"], label: "Falhou / Cancelado" },
];

function agentNameFor(agentId: string | null, agents: Record<string, { name: string }>): string {
  if (!agentId) return "—";
  return agents[agentId]?.name ?? agentId;
}

export function OfficeTaskBoard() {
  // Select the raw, referentially-stable array from the store and filter
  // locally in a memo -- a selector that returns a fresh array every call
  // (e.g. `.filter()` inline) makes `useSyncExternalStore` believe the
  // snapshot changes every render, which is an infinite loop, not just
  // a performance issue.
  const allSteps = useOfficeStore((s) => s.steps);
  const agents = useOfficeStore((s) => s.agents);
  const steps = useMemo(() => allSteps.filter((step) => step.kind === "work"), [allSteps]);

  if (steps.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-xs text-muted-foreground">
        Nenhuma tarefa em andamento. Envie um objetivo em Tarefas para ver o quadro aqui.
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="flex flex-col gap-3 p-3">
        {COLUMNS.map((column) => {
          const columnSteps = steps.filter((s) => column.status.includes(s.status));
          return (
            <div key={column.label}>
              <p className="mb-1.5 text-xs font-semibold text-muted-foreground">
                {column.label} ({columnSteps.length})
              </p>
              <div className="flex flex-col gap-1.5">
                {columnSteps.map((step) => (
                  <TaskCard key={step.id} step={step} agentName={agentNameFor(step.agent_id, agents)} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}

function TaskCard({ step, agentName }: { step: ExecutionStep; agentName: string }) {
  return (
    <div className="rounded-md border border-border bg-background p-2 text-xs">
      <p className="font-medium">{step.name}</p>
      <p className="text-muted-foreground">{agentName}</p>
    </div>
  );
}
