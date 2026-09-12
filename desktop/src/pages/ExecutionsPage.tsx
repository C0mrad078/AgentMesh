import { useEffect, useState } from "react";
import { History, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { executionsApi } from "@/services/api";
import { useSelectedProject } from "@/stores/projectsStore";
import type { Execution, ExecutionStep, ExecutionUsageSummary, RoutingDecisionRecord } from "@/types";

const STATUS_VARIANT: Record<string, "success" | "destructive" | "secondary"> = {
  completed: "success",
  failed: "destructive",
  cancelled: "destructive",
  running: "secondary",
  queued: "secondary",
};

function formatDuration(execution: Execution): string {
  if (!execution.started_at) return "-";
  const end = execution.completed_at ? new Date(execution.completed_at) : new Date();
  const start = new Date(execution.started_at);
  const seconds = Math.max(0, (end.getTime() - start.getTime()) / 1000);
  return seconds < 1 ? "<1s" : `${seconds.toFixed(1)}s`;
}

function ExecutionRow({ execution }: { execution: Execution }) {
  const [steps, setSteps] = useState<ExecutionStep[] | null>(null);
  const [usage, setUsage] = useState<ExecutionUsageSummary | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const [routing, setRouting] = useState<RoutingDecisionRecord[] | null>(null);

  async function toggle() {
    const next = !expanded;
    setExpanded(next);
    if (next && steps === null) {
      const [stepsResult, usageResult] = await Promise.all([
        executionsApi.steps(execution.id),
        executionsApi.usage(execution.id),
      ]);
      setSteps(stepsResult);
      setUsage(usageResult);
    }
  }

  async function toggleDebug() {
    const next = !showDebug;
    setShowDebug(next);
    if (next && routing === null) {
      setRouting(await executionsApi.routing(execution.id));
    }
  }

  return (
    <Card>
      <button className="flex w-full items-center justify-between p-4 text-left" onClick={() => void toggle()}>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium">{execution.id}</span>
          <span className="text-xs text-muted-foreground">
            {new Date(execution.created_at).toLocaleString()} · duração {formatDuration(execution)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {usage && <Badge variant="outline">${usage.total_cost_usd.toFixed(4)}</Badge>}
          <Badge variant={STATUS_VARIANT[execution.status] ?? "secondary"}>{execution.status}</Badge>
        </div>
      </button>
      {expanded && (
        <CardContent className="border-t border-border pt-3">
          {steps === null && <Loader2 className="size-4 animate-spin" />}
          {steps && (
            <ol className="flex flex-col gap-1.5">
              {steps.map((step) => (
                <li key={step.id} className="flex items-center justify-between text-xs">
                  <span>
                    {step.kind === "phase" ? step.name : `↳ ${step.name}`}
                    {step.attempt > 1 && ` (tentativa ${step.attempt})`}
                    {step.provider && ` · ${step.provider}`}
                  </span>
                  <Badge variant={STATUS_VARIANT[step.status] ?? "secondary"}>{step.status}</Badge>
                </li>
              ))}
            </ol>
          )}
          {usage && usage.total_input_tokens + usage.total_output_tokens > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              {usage.total_input_tokens} tokens de entrada · {usage.total_output_tokens} tokens de
              saída · ${usage.total_cost_usd.toFixed(4)}
            </p>
          )}
          {execution.error && (
            <p className="mt-2 text-xs text-destructive">
              {execution.error.message ?? JSON.stringify(execution.error)}
            </p>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="mt-2 h-6 self-start px-2 text-[11px]"
            onClick={() => void toggleDebug()}
          >
            {showDebug ? "Ocultar detalhes técnicos" : "Ver detalhes técnicos"}
          </Button>
          {showDebug && (
            <div className="mt-1 flex flex-col gap-1.5 rounded-md bg-muted p-2">
              {routing === null && <Loader2 className="size-4 animate-spin" />}
              {routing?.length === 0 && (
                <p className="text-xs text-muted-foreground">Nenhuma decisão de roteamento registrada.</p>
              )}
              {routing?.map((decision) => (
                <div key={decision.id} className="text-xs">
                  <span className="font-medium">{decision.agent_id}</span>{" "}
                  <span className="text-muted-foreground">
                    ({decision.provider}/{decision.model}, score {decision.score.toFixed(2)})
                  </span>
                  <p className="text-muted-foreground">{decision.reason}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

export function ExecutionsPage() {
  const project = useSelectedProject();
  const [executions, setExecutions] = useState<Execution[] | null>(null);

  useEffect(() => {
    if (!project) {
      setExecutions(null);
      return;
    }
    setExecutions(null);
    void executionsApi.list(project.id).then(setExecutions);
  }, [project]);

  if (!project) {
    return (
      <EmptyState
        icon={<History className="size-8 text-muted-foreground" />}
        title="Selecione um projeto"
        description="O histórico de execuções é organizado por projeto."
      />
    );
  }

  if (executions === null) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (executions.length === 0) {
    return (
      <EmptyState
        icon={<History className="size-8 text-muted-foreground" />}
        title="Nenhuma execução ainda"
        description="Envie uma tarefa na aba Tarefas para ver o histórico aqui."
      />
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
      {executions.map((execution) => (
        <ExecutionRow key={execution.id} execution={execution} />
      ))}
    </div>
  );
}
