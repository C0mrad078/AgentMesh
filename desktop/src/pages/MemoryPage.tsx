import { useEffect, useState } from "react";
import { Brain, Loader2 } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { memoryApi } from "@/services/api";
import { useSelectedProject } from "@/stores/projectsStore";
import type { MemoryRecordItem } from "@/types";

/**
 * AgentMash V2 (docs/agentmash-v2-migration.md): the first real screen for
 * `core.memory` (Refactor V2 Phase 1 gave it Global/Agent/Session scopes
 * on the backend, but no bridge command exposes those three yet -- see
 * that plan's §7 "Known limitations"). This page only calls the one
 * memory endpoint that already exists and is already wired,
 * `memory.list` (project scope), against whichever project is selected.
 * Real records only -- no fixture data, and an honest empty state instead
 * of a placeholder when a project has none yet.
 */
export function MemoryPage() {
  const project = useSelectedProject();
  const [records, setRecords] = useState<MemoryRecordItem[] | null>(null);

  useEffect(() => {
    if (!project) {
      setRecords(null);
      return;
    }
    setRecords(null);
    void memoryApi.list(project.id).then(setRecords);
  }, [project]);

  if (!project) {
    return (
      <EmptyState
        icon={<Brain className="size-8 text-muted-foreground" />}
        title="Nenhum projeto selecionado"
        description="Selecione um projeto em Projetos para ver a memória dele."
      />
    );
  }

  if (records === null) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <EmptyState
        icon={<Brain className="size-8 text-muted-foreground" />}
        title="Nenhuma memória registrada ainda"
        description={`"${project.name}" ainda não acumulou fatos de projeto.`}
      />
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-1.5">
      <h2 className="mb-1 text-sm font-semibold">Memória — {project.name}</h2>
      {records.map((record) => (
        <div key={record.id} data-testid="memory-record" className="rounded-md border border-border p-3">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="truncate text-sm font-medium">{record.key}</span>
            <Badge variant="outline">{record.category}</Badge>
          </div>
          <pre className="overflow-x-auto whitespace-pre-wrap break-all text-xs text-muted-foreground">
            {JSON.stringify(record.value, null, 2)}
          </pre>
        </div>
      ))}
    </div>
  );
}
