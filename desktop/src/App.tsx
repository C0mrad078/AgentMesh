import { AppShell } from "@/layouts/AppShell";
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

export default function App() {
  useBridgeSubscription();
  const activePage = useUiStore((s) => s.activePage);
  const Page = PAGES[activePage];

  return (
    <AppShell>
      <Page />
    </AppShell>
  );
}
