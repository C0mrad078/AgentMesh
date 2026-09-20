import { lazy, Suspense } from "react";
import { Loader2 } from "lucide-react";
import { AppShell } from "@/layouts/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { TeamPage } from "@/pages/TeamPage";
import { WorkspacePage } from "@/pages/WorkspacePage";
import { ExecutionsPage } from "@/pages/ExecutionsPage";
import { MemoryPage } from "@/pages/MemoryPage";
import { ProvidersPage } from "@/pages/ProvidersPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { LearningPage } from "@/pages/LearningPage";
import { useUiStore } from "@/stores/uiStore";
import { useBridgeSubscription } from "@/hooks/useBridgeSubscription";
import { useOfficeDomainSync } from "@/hooks/useOfficeDomainSync";

// Phaser alone is >1MB minified -- code-split so every other page's
// bundle stays small and the Office's weight is only ever paid by
// visitors who actually open it (spec section 31: the canvas must never
// cost the rest of the app performance).
const OfficePage = lazy(() => import("@/pages/OfficePage").then((m) => ({ default: m.OfficePage })));

const AgentWorkspacePage = lazy(() => import("@/pages/AgentWorkspacePage").then(m => ({ default: m.AgentWorkspacePage })));

const PAGES = {
  collaboration: AgentWorkspacePage,
  office: OfficePage,
  projects: ProjectsPage,
  team: TeamPage,
  workspace: WorkspacePage,
  executions: ExecutionsPage,
  memory: MemoryPage,
  providers: ProvidersPage,
  settings: SettingsPage,
  learning: LearningPage,
};

const PAGE_LABELS: Record<keyof typeof PAGES, string> = {
  collaboration: "Agent Workspace",
  office: "Office",
  projects: "Projetos",
  team: "Equipe",
  workspace: "Tarefas",
  executions: "Execuções",
  memory: "Memória",
  providers: "Providers",
  settings: "Configurações",
  learning: "Aprendizado",
};

export default function App() {
  useBridgeSubscription();
  useOfficeDomainSync();
  const activePage = useUiStore((s) => s.activePage);
  const Page = PAGES[activePage];

  return (
    <AppShell>
      <ErrorBoundary key={activePage} boundaryName={PAGE_LABELS[activePage]}>
        <Suspense fallback={<Loader2 className="m-auto size-6 animate-spin text-muted-foreground" />}>
          <Page />
        </Suspense>
      </ErrorBoundary>
    </AppShell>
  );
}
