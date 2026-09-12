import { AppShell } from "@/layouts/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { WorkspacePage } from "@/pages/WorkspacePage";
import { ExecutionsPage } from "@/pages/ExecutionsPage";
import { AgentsPage } from "@/pages/AgentsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { LearningPage } from "@/pages/LearningPage";
import { useUiStore } from "@/stores/uiStore";
import { useBridgeSubscription } from "@/hooks/useBridgeSubscription";

const PAGES = {
  workspace: WorkspacePage,
  executions: ExecutionsPage,
  agents: AgentsPage,
  settings: SettingsPage,
  learning: LearningPage,
};

const PAGE_LABELS: Record<keyof typeof PAGES, string> = {
  workspace: "Tarefas",
  executions: "Execuções",
  agents: "Agentes",
  settings: "Configurações",
  learning: "Aprendizado",
};

export default function App() {
  useBridgeSubscription();
  const activePage = useUiStore((s) => s.activePage);
  const Page = PAGES[activePage];

  return (
    <AppShell>
      <ErrorBoundary key={activePage} boundaryName={PAGE_LABELS[activePage]}>
        <Page />
      </ErrorBoundary>
    </AppShell>
  );
}
