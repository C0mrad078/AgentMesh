import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TASK_MODES } from "@/types";
import { useUiStore } from "@/stores/uiStore";

export function ModeSelector() {
  const selectedMode = useUiStore((s) => s.selectedMode);
  const setSelectedMode = useUiStore((s) => s.setSelectedMode);

  return (
    <Tabs value={selectedMode} onValueChange={(value) => setSelectedMode(value as typeof selectedMode)}>
      <TabsList>
        {TASK_MODES.map((mode) => (
          <TabsTrigger
            key={mode.value}
            value={mode.value}
            disabled={!mode.available}
            title={mode.available ? undefined : "Disponível em um próximo estágio"}
          >
            {mode.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
