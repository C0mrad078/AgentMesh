import { lazy, Suspense } from "react";
import { Loader2 } from "lucide-react";
import { AppShell } from "@/layouts/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { WorkspacePage } from "@/pages/WorkspacePage";
import { ExecutionsPage } from "@/pages/ExecutionsPage";
import { AgentsPage } from "@/pages/AgentsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { LearningPage } from "@/pages/LearningPage";
import { useUiStore } from "@/stores/uiStore";
import { useBridgeSubscription } from "@/hooks/useBridgeSubscription";
import { useRealOfficeSync } from "@/hooks/useRealOfficeSync";

// Phaser alone is >1MB minified -- code-split so every other page's
// bundle stays small and the Office's weight is only ever paid by
// visitors who actually open it (spec section 31: the canvas must never
// cost the rest of the app performance).
const OfficePage = lazy(() => import("@/pages/OfficePage").then((m) => ({ default: m.OfficePage })));

const PAGES = {
  office: OfficePage,
  workspace: WorkspacePage,
  executions: ExecutionsPage,
  agents: AgentsPage,
  settings: SettingsPage,
  learning: LearningPage,
};

const PAGE_LABELS: Record<keyof typeof PAGES, string> = {
  office: "Office",
  workspace: "Tarefas",
  executions: "Execuções",
  agents: "Agentes",
  settings: "Configurações",
  learning: "Aprendizado",
};

export default function App() {
  useBridgeSubscription();
  useRealOfficeSync();
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
