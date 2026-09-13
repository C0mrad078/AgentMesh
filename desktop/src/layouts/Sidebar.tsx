import { useEffect } from "react";
import { Plus, MessagesSquare, History, Bot, Settings, GraduationCap, Building2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useProjectsStore } from "@/stores/projectsStore";
import { useUiStore, type AppPage } from "@/stores/uiStore";

const NAV_ITEMS: { page: AppPage; label: string; icon: typeof MessagesSquare }[] = [
  { page: "office", label: "Office", icon: Building2 },
  { page: "workspace", label: "Tarefas", icon: MessagesSquare },
  { page: "executions", label: "Execuções", icon: History },
  { page: "agents", label: "Agentes", icon: Bot },
  { page: "learning", label: "Aprendizado", icon: GraduationCap },
  { page: "settings", label: "Configurações", icon: Settings },
];

export function Sidebar() {
  const { projects, selectedProjectId, loading, loaded, error, loadProjects, selectProject } =
    useProjectsStore();
  const activePage = useUiStore((s) => s.activePage);
  const setActivePage = useUiStore((s) => s.setActivePage);
  const setNewProjectDialogOpen = useUiStore((s) => s.setNewProjectDialogOpen);

  useEffect(() => {
    if (!loaded) void loadProjects();
  }, [loaded, loadProjects]);

  return (
    <aside className="flex h-full w-64 flex-col border-r border-border bg-card" data-testid="sidebar">
      <div className="flex items-center justify-between p-3">
        <span className="text-sm font-semibold tracking-tight">Orquestrador</span>
      </div>

      <Separator />

      <nav className="flex flex-col gap-0.5 p-2">
        {NAV_ITEMS.map(({ page, label, icon: Icon }) => (
          <Button
            key={page}
            variant={activePage === page ? "secondary" : "ghost"}
            className="justify-start"
            onClick={() => setActivePage(page)}
            data-testid={`nav-${page}`}
          >
            <Icon className="size-4" />
            {label}
          </Button>
        ))}
      </nav>

      <Separator />

      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">Projetos</span>
        <Button
          size="icon"
          variant="ghost"
          className="size-6"
          onClick={() => setNewProjectDialogOpen(true)}
          aria-label="Novo projeto"
          data-testid="new-project-button"
        >
          <Plus className="size-4" />
        </Button>
      </div>

      <ScrollArea className="flex-1 px-2">
        {loading && <p className="px-2 py-4 text-xs text-muted-foreground">Carregando projetos...</p>}
        {!loading && error && (
          <div className="flex flex-col gap-2 px-2 py-4">
            <p className="text-xs text-destructive">Falha ao carregar projetos: {error}</p>
            <Button size="sm" variant="outline" onClick={() => void loadProjects()}>
              Tentar novamente
            </Button>
          </div>
        )}
        {!loading && !error && loaded && projects.length === 0 && (
          <p className="px-2 py-4 text-xs text-muted-foreground">
            Nenhum projeto ainda. Crie o primeiro para começar.
          </p>
        )}
        <div className="flex flex-col gap-0.5 pb-3">
          {projects.map((project) => (
            <button
              key={project.id}
              onClick={() => {
                selectProject(project.id);
                setActivePage("workspace");
              }}
              className={cn(
                "truncate rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent",
                selectedProjectId === project.id && "bg-accent font-medium",
              )}
              data-testid="project-item"
            >
              {project.name}
            </button>
          ))}
        </div>
      </ScrollArea>
    </aside>
  );
}
