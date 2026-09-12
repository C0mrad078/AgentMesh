import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { budgetApi } from "@/services/api";
import type { BudgetLimits } from "@/types";

function toInputValue(value: number | null): string {
  return value === null ? "" : String(value);
}

function parseLimit(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function BudgetSettings() {
  const [limits, setLimits] = useState<BudgetLimits | null>(null);
  const [draft, setDraft] = useState({ perExecution: "", daily: "", monthly: "" });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void budgetApi.get().then((result) => {
      setLimits(result);
      setDraft({
        perExecution: toInputValue(result.max_per_execution_usd),
        daily: toInputValue(result.daily_limit_usd),
        monthly: toInputValue(result.monthly_limit_usd),
      });
    });
  }, []);

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    try {
      const updated = await budgetApi.set({
        max_per_execution_usd: parseLimit(draft.perExecution),
        daily_limit_usd: parseLimit(draft.daily),
        monthly_limit_usd: parseLimit(draft.monthly),
      });
      setLimits(updated);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  }

  if (limits === null) {
    return <Loader2 className="size-5 animate-spin text-muted-foreground" />;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="budget-per-execution">Máximo por execução (USD)</Label>
          <Input
            id="budget-per-execution"
            type="number"
            min="0"
            step="0.01"
            placeholder="Sem limite"
            value={draft.perExecution}
            onChange={(e) => setDraft((d) => ({ ...d, perExecution: e.target.value }))}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="budget-daily">Limite diário (USD)</Label>
          <Input
            id="budget-daily"
            type="number"
            min="0"
            step="0.01"
            placeholder="Sem limite"
            value={draft.daily}
            onChange={(e) => setDraft((d) => ({ ...d, daily: e.target.value }))}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="budget-monthly">Limite mensal (USD)</Label>
          <Input
            id="budget-monthly"
            type="number"
            min="0"
            step="0.01"
            placeholder="Sem limite"
            value={draft.monthly}
            onChange={(e) => setDraft((d) => ({ ...d, monthly: e.target.value }))}
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={saving} onClick={() => void handleSave()}>
          {saving ? <Loader2 className="size-4 animate-spin" /> : "Salvar limites"}
        </Button>
        {saved && <span className="text-xs text-success">Salvo.</span>}
      </div>
      <p className="text-xs text-muted-foreground">
        Ao atingir 80% de um limite configurado, o Orquestrador tenta simplificar a estratégia.
        Ao atingir 100%, novas chamadas de IA são bloqueadas até o limite ser aumentado ou
        reiniciado (diário/mensal).
      </p>
    </div>
  );
}
