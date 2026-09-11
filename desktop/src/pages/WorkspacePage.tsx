import { useState } from "react";
import { FolderPlus, Loader2, Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/EmptyState";
import { ModeSelector } from "@/components/ModeSelector";
import { StepBoard } from "@/components/StepBoard";
import { useSelectedProject } from "@/stores/projectsStore";
import { useUiStore } from "@/stores/uiStore";
import { useExecutionStore } from "@/stores/executionStore";
import { useConnectionStatus } from "@/hooks/useConnectionStatus";

const TASK_STATUS_LABEL: Record<string, string> = {
  queued: "Na fila",
  running: "Em execução",
  waiting: "Aguardando",
  reviewing: "Em revisão",
  completed: "Concluída",
  failed: "Falhou",
  cancelled: "Cancelada",
};

export function WorkspacePage() {
  const project = useSelectedProject();
  const setNewProjectDialogOpen = useUiStore((s) => s.setNewProjectDialogOpen);
  const selectedMode = useUiStore((s) => s.selectedMode);
  const { isConnected } = useConnectionStatus();

  const { submitTask, cancelActive, submitting, phases, task, error } = useExecutionStore();
  const [title, setTitle] = useState("");

  if (!project) {
    return (
      <EmptyState
        icon={<FolderPlus className="size-8 text-muted-foreground" />}
        title="Nenhum projeto selecionado"
        description="Crie ou selecione um projeto na barra lateral para começar a enviar tarefas ao Orquestrador."
        action={<Button onClick={() => setNewProjectDialogOpen(true)}>Novo projeto</Button>}
      />
    );
  }

  const isRunning = task ? !["completed", "failed", "cancelled"].includes(task.status) : false;

  async function handleSubmit() {
    if (!title.trim() || !project) return;
    await submitTask({ projectId: project.id, title: title.trim(), mode: selectedMode });
    setTitle("");
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">{project.name}</h2>
          {project.description && (
            <p className="text-xs text-muted-foreground">{project.description}</p>
          )}
        </div>
        <ModeSelector />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Nova tarefa</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Textarea
            placeholder="Descreva o objetivo que o Orquestrador deve cumprir..."
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={submitting || isRunning}
          />
          <div className="flex justify-end gap-2">
            {isRunning ? (
              <Button variant="destructive" onClick={() => void cancelActive()}>
                <Square className="size-4" />
                Cancelar
              </Button>
            ) : (
              <Button onClick={() => void handleSubmit()} disabled={!isConnected || !title.trim() || submitting}>
                {submitting ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                Enviar tarefa
              </Button>
            )}
          </div>
          {!isConnected && (
            <p className="text-xs text-warning">
              O core do Orquestrador ainda não está conectado. Aguarde ou reconecte.
            </p>
          )}
          {error && <p className="text-xs text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {(phases.length > 0 || task) && (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle>Progresso</CardTitle>
            {task && (
              <Badge
                variant={
                  task.status === "completed"
                    ? "success"
                    : task.status === "failed" || task.status === "cancelled"
                      ? "destructive"
                      : "secondary"
                }
              >
                {TASK_STATUS_LABEL[task.status]}
              </Badge>
            )}
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <StepBoard phases={phases} />
            {task?.result && (
              <div className="rounded-md bg-muted p-3 text-sm">
                <p className="mb-1 text-xs font-medium text-muted-foreground">Resultado</p>
                <pre className="whitespace-pre-wrap break-words font-sans text-sm">
                  {typeof task.result.summary === "string"
                    ? task.result.summary
                    : JSON.stringify(task.result, null, 2)}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
