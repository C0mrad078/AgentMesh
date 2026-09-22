import {
  Building2, FolderKanban, Users, MessagesSquare, History, Brain, Plug, GraduationCap, Settings, Cpu, Activity, Rocket,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useUiStore, type AppPage } from "@/stores/uiStore";

const NAV_ITEMS: { page: AppPage; label: string; icon: typeof Building2 }[] = [
  { page: "collaboration", label: "Workspace", icon: MessagesSquare },
  { page: "office", label: "Office", icon: Building2 },
  { page: "projects", label: "Projetos", icon: FolderKanban },
  { page: "team", label: "Equipe", icon: Users },
  { page: "workspace", label: "Tarefas", icon: MessagesSquare },
  { page: "executions", label: "Execuções", icon: History },
  { page: "memory", label: "Memória", icon: Brain },
  { page: "providers", label: "Providers", icon: Plug },
  { page: "runtime-bindings", label: "Runtimes", icon: Cpu },
  { page: "learning", label: "Aprendizado", icon: GraduationCap },
  { page: "diagnostics", label: "Diagnósticos", icon: Activity },
  { page: "onboarding", label: "Onboarding", icon: Rocket },
  { page: "settings", label: "Config.", icon: Settings },
];


/**
 * AgentMash V2 (docs/agentmash-v2-migration.md): replaces the V1 fixed
 * w-64 left `Sidebar` entirely -- a thin bottom strip, matching the
 * brief's own reference mockup (`Office Projects Team Tasks Memory
 * Providers`), so the Office canvas above it owns almost the entire
 * window instead of sharing it with a permanent SaaS-style rail.
 */
export function BottomNav() {
  const activePage = useUiStore((s) => s.activePage);
  const setActivePage = useUiStore((s) => s.setActivePage);

  return (
    <nav
      className="flex h-12 shrink-0 items-center gap-0.5 overflow-x-auto border-t border-border bg-card/60 px-1.5"
      data-testid="bottom-nav"
    >
      {NAV_ITEMS.map(({ page, label, icon: Icon }) => {
        const active = activePage === page;
        return (
          <button
            key={page}
            type="button"
            onClick={() => setActivePage(page)}
            data-testid={`nav-${page}`}
            className={cn(
              "flex shrink-0 flex-col items-center justify-center gap-0.5 rounded-md px-2.5 py-1 text-[11px] leading-none transition-colors",
              active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50",
            )}
          >
            <Icon className="size-4" />
            {label}
          </button>
        );
      })}
    </nav>
  );
}
