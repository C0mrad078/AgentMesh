import { useEffect } from "react";
import { FolderKanban, Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { useProjectsStore } from "@/stores/projectsStore";
import { useUiStore } from "@/stores/uiStore";

/**
 * AgentMash V2 (docs/agentmash-v2-migration.md): replaces the V1
 * `Sidebar`'s project list (a fixed rail always on screen) with a real
 * page -- "Project = workplace" (V2 brief), each card a real project from
 * `projectsStore`, no fake data. Per-project team/memory/session counts
 * from the brief's own mockup aren't wired yet (no bridge command
 * aggregates them) -- shown honestly as just name/path/description today
 * rather than inventing numbers.
 */
export function ProjectsPage() {
  const { projects, selectedProjectId, loading, loaded, error, loadProjects, selectProject } =
    useProjectsStore();
  const setActivePage = useUiStore((s) => s.setActivePage);
  const setNewProjectDialogOpen = useUiStore((s) => s.setNewProjectDialogOpen);

  useEffect(() => {
    if (!loaded) void loadProjects();
  }, [loaded, loadProjects]);

  function enterWorkspace(projectId: string) {
    selectProject(projectId);
    setActivePage("collaboration");
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Projetos</h2>
        <Button size="sm" onClick={() => setNewProjectDialogOpen(true)}>
          <Plus className="size-4" /> Novo projeto
        </Button>
      </div>

      {loading && (
        <div className="flex flex-1 items-center justify-center py-10">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {!loading && error && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border p-6 text-center">
          <p className="text-xs text-destructive">Falha ao carregar projetos: {error}</p>
          <Button size="sm" variant="outline" className="mx-auto" onClick={() => void loadProjects()}>
            Tentar novamente
          </Button>
        </div>
      )}

      {!loading && !error && loaded && projects.length === 0 && (
        <EmptyState
          icon={<FolderKanban className="size-8 text-muted-foreground" />}
          title="Nenhum projeto ainda"
          description="Crie o primeiro projeto para dar um workspace real à sua equipe de agentes."
          action={
            <Button size="sm" onClick={() => setNewProjectDialogOpen(true)}>
              <Plus className="size-4" /> Novo projeto
            </Button>
          }
        />
      )}

      {!loading && !error && projects.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {projects.map((project) => (
            <Card key={project.id} data-testid="project-card">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {project.name}
                  {selectedProjectId === project.id && (
                    <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-normal text-accent-foreground">
                      selecionado
                    </span>
                  )}
                </CardTitle>
                {project.workspace_path && (
                  <CardDescription className="truncate font-mono text-[11px]">
                    {project.workspace_path}
                  </CardDescription>
                )}
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {project.description && (
                  <p className="text-xs text-muted-foreground">{project.description}</p>
                )}
                <Button size="sm" variant="secondary" onClick={() => enterWorkspace(project.id)}>
                  Abrir Workspace
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
