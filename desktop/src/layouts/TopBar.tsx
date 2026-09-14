import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { useUiStore } from "@/stores/uiStore";

/**
 * AgentMash V2 (docs/agentmash-v2-migration.md): a slim strip, not a
 * dashboard header -- brand + real connection status + "new project" on
 * the right. No page title here (the page itself says what it is), no
 * fixed-width sidebar living below it. Together with `BottomNav`, this
 * leaves the Office ~85-90% of the window, exactly the ratio the V2 brief
 * requires instead of the V1 header+sidebar shell.
 */
export function TopBar() {
  const setNewProjectDialogOpen = useUiStore((s) => s.setNewProjectDialogOpen);

  return (
    <header className="flex h-9 shrink-0 items-center justify-between border-b border-border bg-card/60 px-3">
      <span className="text-sm font-semibold tracking-tight">AgentMash</span>
      <div className="flex items-center gap-2">
        <ConnectionBadge />
        <Button
          size="icon"
          variant="ghost"
          className="size-6"
          aria-label="Novo projeto"
          onClick={() => setNewProjectDialogOpen(true)}
        >
          <Plus className="size-4" />
        </Button>
      </div>
    </header>
  );
}
