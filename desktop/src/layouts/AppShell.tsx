import type { ReactNode } from "react";
import { Sidebar } from "@/layouts/Sidebar";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { NewProjectDialog } from "@/components/NewProjectDialog";
import { useUiStore, type AppPage } from "@/stores/uiStore";

const PAGE_TITLES: Record<AppPage, string> = {
  workspace: "Tarefas",
  executions: "Execuções",
  agents: "Agentes",
  settings: "Configurações",
  learning: "Aprendizado",
};

export function AppShell({ children }: { children: ReactNode }) {
  const activePage = useUiStore((s) => s.activePage);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
          <h1 className="text-sm font-semibold">{PAGE_TITLES[activePage]}</h1>
          <ConnectionBadge />
        </header>
        <main className="flex min-h-0 flex-1 flex-col overflow-auto p-4">{children}</main>
      </div>
      <NewProjectDialog />
    </div>
  );
}
