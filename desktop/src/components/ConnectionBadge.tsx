import { Loader2, CheckCircle2, AlertTriangle, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useConnectionStatus } from "@/hooks/useConnectionStatus";
import { useConnectionStore } from "@/stores/connectionStore";
import { cn } from "@/lib/utils";

const ICONS: Record<string, typeof Loader2> = {
  neutral: Loader2,
  success: CheckCircle2,
  warning: AlertTriangle,
  destructive: WifiOff,
};

const TONE_CLASSES: Record<string, string> = {
  neutral: "text-muted-foreground",
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
};

export function ConnectionBadge() {
  const { label, tone, canRetry } = useConnectionStatus();
  const reconnect = useConnectionStore((s) => s.reconnect);
  const Icon = ICONS[tone];
  const spinning = tone === "neutral";

  return (
    <div className="flex items-center gap-2 text-xs" data-testid="connection-badge">
      <Icon className={cn("size-3.5", TONE_CLASSES[tone], spinning && "animate-spin")} />
      <span className={TONE_CLASSES[tone]}>{label}</span>
      {canRetry && (
        <Button variant="outline" size="sm" className="h-6 px-2 text-[11px]" onClick={() => void reconnect()}>
          Reconectar
        </Button>
      )}
    </div>
  );
}
