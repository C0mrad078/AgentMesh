import { useRef, useState } from "react";
import { Bug, Minus, Plus, Maximize, LocateFixed, RotateCcw, Wrench } from "lucide-react";
import { PhaserOffice, type PhaserOfficeHandle } from "@/components/PhaserOffice";
import { AgentDetailPanel } from "@/components/AgentDetailPanel";
import { Button } from "@/components/ui/button";
import { useUiStore } from "@/stores/uiStore";
import type { AgentInspectInfo, OfficeSummary } from "@/game/scenes/OfficeScene";
import { officeSimulationService } from "@/game/simulation/OfficeSimulationService";

const EMPTY_SUMMARY: OfficeSummary = { working: 0, meeting: 0, resting: 0, sleeping: 0, waiting: 0, error: 0, idle: 0 };

/**
 * Fullscreen, observer-only view of the autonomous office (spec section
 * 30/50): the user commands the camera and, in Developer Mode, the
 * simulation debug controls -- never a character. Clicking/hovering an
 * agent only opens read-only info (spec section 32/34/35).
 */
export function OfficePage() {
  const setActivePage = useUiStore((s) => s.setActivePage);
  const [summary, setSummary] = useState<OfficeSummary>(EMPTY_SUMMARY);
  const [hoveredAgent, setHoveredAgent] = useState<AgentInspectInfo | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<AgentInspectInfo | null>(null);
  const [followingAgentId, setFollowingAgentId] = useState<string | null>(null);
  const [devMode, setDevMode] = useState(false);
  const phaserRef = useRef<PhaserOfficeHandle>(null);

  function refreshSelected() {
    if (!selectedAgent) return;
    const updated = phaserRef.current?.inspect(selectedAgent.id);
    if (updated) setSelectedAgent(updated);
  }

  function handleSummaryChange(next: OfficeSummary) {
    setSummary(next);
    refreshSelected();
  }

  function handleFollow(agentId: string) {
    phaserRef.current?.followAgent(agentId);
    setFollowingAgentId(agentId);
  }

  function handleStopFollow() {
    phaserRef.current?.stopFollow();
    setFollowingAgentId(null);
  }

  return (
    <div className="relative h-full w-full">
      <PhaserOffice
        ref={phaserRef}
        onHoverAgent={(id) => setHoveredAgent(id ? (phaserRef.current?.inspect(id) ?? null) : null)}
        onClickAgent={(id) => {
          const info = phaserRef.current?.inspect(id);
          if (info) setSelectedAgent(info);
        }}
        onTaskBoardClick={() => setActivePage("workspace")}
        onSummaryChange={handleSummaryChange}
      />

      <div className="pointer-events-none absolute left-3 top-3">
        <div className="pointer-events-auto flex items-center gap-3 rounded-md border border-border bg-card/85 px-3 py-1.5 text-xs text-muted-foreground shadow backdrop-blur">
          <span>{summary.working} trabalhando</span>
          <span>{summary.meeting} em reunião</span>
          <span>{summary.resting} descansando</span>
          <span>{summary.sleeping} dormindo</span>
          {summary.waiting > 0 && <span>{summary.waiting} aguardando</span>}
          {summary.error > 0 && <span className="text-destructive">{summary.error} com erro</span>}
        </div>
      </div>

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
        <Button
          size="icon"
          variant={devMode ? "secondary" : "ghost"}
          className="size-7"
          aria-label="Alternar Developer Mode"
          onClick={() => setDevMode((v) => !v)}
        >
          <Wrench className="size-3.5" />
        </Button>
        <Button size="icon" variant="ghost" className="size-7" aria-label="Alternar modo debug (tecla `)" onClick={() => phaserRef.current?.toggleDebug()}>
          <Bug className="size-3.5" />
        </Button>
      </div>

      {devMode && (
        <div className="absolute bottom-3 left-3 flex max-w-[calc(100%-1.5rem)] flex-wrap gap-1.5 rounded-md border border-border bg-card/95 p-2 shadow-lg backdrop-blur">
          <DevButton label="Start Workday" onClick={() => officeSimulationService.startWorkday()} />
          <DevButton label="Start Planning Meeting" onClick={() => officeSimulationService.startPlanningMeeting()} />
          <DevButton label="End Meeting" onClick={() => officeSimulationService.endMeeting()} />
          <DevButton label="Rate Limit Codex" onClick={() => officeSimulationService.rateLimitShort("agent_codex", "codex_cli")} />
          <DevButton label="Long Cooldown Claude" onClick={() => officeSimulationService.rateLimitLong("agent_claude_code", "claude_code_cli")} />
          <DevButton label="Recover Codex" onClick={() => officeSimulationService.recover("agent_codex")} />
          <DevButton label="Recover Claude" onClick={() => officeSimulationService.recover("agent_claude_code")} />
          <DevButton label="Send to Testing" onClick={() => officeSimulationService.sendToTesting("agent_claude_code")} />
          <DevButton label="Trigger Error" onClick={() => officeSimulationService.triggerError("agent_codex", "Falha simulada")} />
          <DevButton label="Complete Task" onClick={() => officeSimulationService.completeTask("agent_codex")} />
          <DevButton label="Reset Office" onClick={() => officeSimulationService.resetOffice()} />
        </div>
      )}

      {hoveredAgent && !selectedAgent && (
        <div className="pointer-events-none absolute bottom-3 right-3 max-w-xs rounded-md border border-border bg-card/95 p-3 text-xs shadow-lg backdrop-blur">
          <p className="font-semibold">{hoveredAgent.name}</p>
          <p className="text-muted-foreground">{hoveredAgent.roleLabel}</p>
          <p className="mt-1">Status: {hoveredAgent.state}</p>
          {hoveredAgent.taskTitle && <p className="text-muted-foreground">{hoveredAgent.taskTitle}</p>}
        </div>
      )}

      {selectedAgent && (
        <div className="absolute right-3 top-16">
          <AgentDetailPanel
            agent={selectedAgent}
            onClose={() => setSelectedAgent(null)}
            onFollow={() => handleFollow(selectedAgent.id)}
            following={followingAgentId === selectedAgent.id}
          />
        </div>
      )}
    </div>
  );
}

function DevButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onClick}>
      {label}
    </Button>
  );
}
