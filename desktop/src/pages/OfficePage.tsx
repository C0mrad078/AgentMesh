import { useMemo, useRef, useState } from "react";
import { Minus, Plus, Maximize, LocateFixed, RotateCcw } from "lucide-react";
import { PhaserOffice, type PhaserOfficeHandle } from "@/components/PhaserOffice";
import { AgentDetailPanel } from "@/components/AgentDetailPanel";
import { OfficeTaskBoard } from "@/components/OfficeTaskBoard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useOfficeStore } from "@/stores/officeStore";
import { useUiStore, type AppPage } from "@/stores/uiStore";
import { roomLabel } from "@/office/map";

const WORKING_STATES = new Set(["WORKING", "TESTING", "REVIEWING", "PLANNING", "MEETING"]);
const WAITING_STATES = new Set(["WAITING", "BLOCKED", "RATE_LIMITED", "RESTING"]);

// Real navigation only -- clicking the in-canvas Task Board object opens
// the app's actual Tasks page, never a fake in-canvas panel duplicating
// data (spec section 43/48).
const OBJECT_DESTINATIONS: Record<string, AppPage> = {
  task_board: "workspace",
};

export function OfficePage() {
  const agents = useOfficeStore((s) => s.agents);
  const error = useOfficeStore((s) => s.error);
  const setActivePage = useUiStore((s) => s.setActivePage);
  const [hoveredAgentId, setHoveredAgentId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [followingAgentId, setFollowingAgentId] = useState<string | null>(null);
  const phaserRef = useRef<PhaserOfficeHandle>(null);

  const stats = useMemo(() => {
    const values = Object.values(agents);
    const online = values.filter((a) => a.state !== "OFFLINE").length;
    const working = values.filter((a) => WORKING_STATES.has(a.state)).length;
    const waiting = values.filter((a) => WAITING_STATES.has(a.state)).length;
    return { online, working, waiting, total: values.length };
  }, [agents]);

  const hovered = hoveredAgentId ? agents[hoveredAgentId] : null;

  function handleFollow(agentId: string) {
    phaserRef.current?.followAgent(agentId);
    setFollowingAgentId(agentId);
  }

  function handleStopFollow() {
    phaserRef.current?.stopFollow();
    setFollowingAgentId(null);
  }

  return (
    <div className="flex h-full gap-3">
      <div className="flex flex-1 flex-col gap-3">
        <Card className="flex items-center gap-4 px-4 py-2 text-xs text-muted-foreground">
          <span>{stats.online} agentes online</span>
          <span>{stats.working} trabalhando</span>
          <span>{stats.waiting} aguardando/rate limit</span>
        </Card>

        {error && (
          <Card className="border-destructive/50 px-4 py-2 text-xs text-destructive">
            Falha ao carregar o escritório: {error}
          </Card>
        )}

        <div className="relative flex-1 overflow-hidden rounded-lg border border-border">
          <PhaserOffice
            ref={phaserRef}
            onHoverAgent={setHoveredAgentId}
            onClickAgent={(agentId) => {
              setSelectedAgentId(agentId);
              if (followingAgentId) handleFollow(agentId);
            }}
            onInteractiveObjectClick={(objectId) => {
              const page = OBJECT_DESTINATIONS[objectId];
              if (page) setActivePage(page);
            }}
          />

          <div className="absolute right-3 top-3 flex flex-col gap-1 rounded-md border border-border bg-card/90 p-1 shadow-lg backdrop-blur">
            <Button size="icon" variant="ghost" className="size-7" aria-label="Aumentar zoom" onClick={() => phaserRef.current?.zoomIn()}>
              <Plus className="size-4" />
            </Button>
            <Button size="icon" variant="ghost" className="size-7" aria-label="Diminuir zoom" onClick={() => phaserRef.current?.zoomOut()}>
              <Minus className="size-4" />
            </Button>
            <Button size="icon" variant="ghost" className="size-7" aria-label="Ajustar à tela" onClick={() => phaserRef.current?.fit()}>
              <Maximize className="size-4" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="size-7"
              aria-label="Redefinir câmera"
              onClick={() => {
                phaserRef.current?.reset();
                setFollowingAgentId(null);
              }}
            >
              <RotateCcw className="size-4" />
            </Button>
            {followingAgentId && (
              <Button size="icon" variant="secondary" className="size-7" aria-label="Parar de seguir" onClick={handleStopFollow}>
                <LocateFixed className="size-4" />
              </Button>
            )}
          </div>

          {hovered && (
            <div className="pointer-events-none absolute bottom-3 left-3 max-w-xs rounded-md border border-border bg-card/95 p-3 text-xs shadow-lg backdrop-blur">
              <p className="font-semibold">{hovered.name}</p>
              <p className="text-muted-foreground">{roomLabel(hovered.homeRoom)}</p>
              <p className="mt-1">Status: {hovered.state}</p>
              {hovered.statusDetail && <p className="text-muted-foreground">{hovered.statusDetail}</p>}
              <p className="text-muted-foreground">Provider: {hovered.provider}</p>
            </div>
          )}
        </div>
      </div>

      <div className="flex w-64 flex-col">
        <Card className="flex-1 overflow-hidden p-0">
          <OfficeTaskBoard />
        </Card>
      </div>

      {selectedAgentId && (
        <AgentDetailPanel
          agentId={selectedAgentId}
          onClose={() => setSelectedAgentId(null)}
          onFollow={() => handleFollow(selectedAgentId)}
          following={followingAgentId === selectedAgentId}
        />
      )}
    </div>
  );
}
