import { useEffect, useState } from "react";
import { Bot, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { agentsApi } from "@/services/api";
import type { Agent } from "@/types";

export function AgentsPage() {
  const [agents, setAgents] = useState<Agent[] | null>(null);

  useEffect(() => {
    void agentsApi.list().then(setAgents);
  }, []);

  if (agents === null) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <EmptyState
        icon={<Bot className="size-8 text-muted-foreground" />}
        title="Nenhum agente configurado"
      />
    );
  }

  return (
    <div className="mx-auto grid w-full max-w-3xl grid-cols-1 gap-3 sm:grid-cols-2">
      {agents.map((agent) => (
        <Card key={agent.id}>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle>{agent.name}</CardTitle>
              <CardDescription>{agent.provider} · {agent.model || "mock"}</CardDescription>
            </div>
            <Badge variant={agent.active ? "success" : "secondary"}>
              {agent.active ? "Ativo" : "Inativo"}
            </Badge>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground">{agent.description}</p>
            <div className="flex flex-wrap gap-1.5">
              {agent.capabilities.map((cap) => (
                <Badge key={cap.name} variant="outline">
                  {cap.name}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
