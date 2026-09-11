import { GraduationCap } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";

export function LearningPage() {
  return (
    <EmptyState
      icon={<GraduationCap className="size-8 text-muted-foreground" />}
      title="Aprendizado chegará em um próximo estágio"
      description="Aqui o Orquestrador mostrará regras aprendidas a partir de execuções passadas (o que funcionou, o que precisou de correção, padrões por projeto). A arquitetura de dados (learned_rules, project_memories) já existe; a experiência de aprendizado ainda não."
    />
  );
}
