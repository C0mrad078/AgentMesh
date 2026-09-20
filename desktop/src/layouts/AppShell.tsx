import type { ReactNode } from "react";
import { TopBar } from "@/layouts/TopBar";
import { BottomNav } from "@/layouts/BottomNav";
import { NewProjectDialog } from "@/components/NewProjectDialog";
import { useUiStore } from "@/stores/uiStore";

/**
 * AgentMash V2 shell (docs/agentmash-v2-migration.md): no fixed-width
 * dashboard sidebar, no per-page header stealing vertical space -- just a
 * slim top strip and a slim bottom nav, so whatever page is active (the
 * Office, above all) gets essentially the whole window. The V1 `Sidebar`
 * component this replaced is deleted, not hidden behind a flag: nothing
 * in V2 still depends on it.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const activePage = useUiStore((s) => s.activePage);
  // The Office is a real 2D world -- it never gets the padded/scrolling
  // treatment every other (still page-shaped) screen uses.
  const isOffice = (activePage === "office" || activePage === "collaboration");

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-background text-foreground">
      <TopBar />
      <main className={isOffice ? "relative min-h-0 flex-1" : "flex min-h-0 flex-1 flex-col overflow-auto p-4"}>
        {children}
      </main>
      <BottomNav />
      <NewProjectDialog />
    </div>
  );
}
