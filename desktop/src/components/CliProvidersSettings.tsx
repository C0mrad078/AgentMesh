import { useEffect, useState } from "react";
import { CheckCircle2, HelpCircle, Loader2, RefreshCw, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { providerCliApi } from "@/services/api";
import type { CliProviderName, CliProviderStatus, ProviderConnectionState } from "@/types";

const CLI_PROVIDER_LABELS: Record<CliProviderName, { name: string; installHint: string }> = {
  codex_cli: {
    name: "Codex CLI",
    installHint: "npm install -g @openai/codex",
  },
  claude_code_cli: {
    name: "Claude Code CLI",
    installHint: "veja claude.com/code para o instalador oficial",
  },
  gemini_cli: {
    name: "Gemini CLI",
    installHint: "veja a documentação oficial do Gemini CLI",
  },
};

const CLI_PROVIDER_ORDER: CliProviderName[] = ["codex_cli", "claude_code_cli", "gemini_cli"];

const STATE_BADGE: Record<ProviderConnectionState, { label: string; variant: "success" | "warning" | "secondary" | "destructive" }> = {
  connected: { label: "Conectado", variant: "success" },
  disconnected: { label: "Não autenticado", variant: "warning" },
  not_installed: { label: "Não instalado", variant: "secondary" },
  error: { label: "Erro", variant: "destructive" },
};

function StateIcon({ state }: { state: ProviderConnectionState }) {
  if (state === "connected") return <CheckCircle2 className="size-3.5" />;
  if (state === "not_installed") return <HelpCircle className="size-3.5" />;
  return <XCircle className="size-3.5" />;
}

export function CliProvidersSettings() {
  const [statuses, setStatuses] = useState<Record<CliProviderName, CliProviderStatus> | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    setRefreshing(true);
    setError(null);
    try {
      const result = await providerCliApi.listStatuses();
      setStatuses(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  if (statuses === null && !error) {
    return <Loader2 className="size-5 animate-spin text-muted-foreground" />;
  }

  return (
    <div className="flex flex-col gap-3">
      {error && <p className="text-xs text-destructive">{error}</p>}
      {CLI_PROVIDER_ORDER.map((name) => {
        const status = statuses?.[name];
        const label = CLI_PROVIDER_LABELS[name];
        const badge = status ? STATE_BADGE[status.state] : null;
        return (
          <Card key={name}>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle>{label.name}</CardTitle>
                <CardDescription>
                  {status ? (
                    <span className="inline-flex items-center gap-1">
                      <StateIcon state={status.state} />
                      {status.version ? `Versão ${status.version}` : "Autenticação via CLI oficial"}
                    </span>
                  ) : (
                    "Verificando..."
                  )}
                </CardDescription>
              </div>
              {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {status?.state === "connected" && (
                <p className="text-xs text-muted-foreground">
                  Método: {status.auth_method ?? "desconhecido"}
                  {status.model ? ` · Modelo: ${status.model}` : ""}
                </p>
              )}
              {status?.state === "not_installed" && (
                <p className="text-xs text-muted-foreground">
                  Instale com: <code className="rounded bg-muted px-1 py-0.5">{label.installHint}</code>
                </p>
              )}
              {status?.detail && status.state !== "connected" && status.state !== "not_installed" && (
                <p className="text-xs text-muted-foreground">{status.detail}</p>
              )}
              <div>
                <Button variant="outline" size="sm" disabled={refreshing} onClick={() => void reload()}>
                  {refreshing ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <span className="inline-flex items-center gap-1.5">
                      <RefreshCw className="size-3.5" /> Verificar novamente
                    </span>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        );
      })}
      <p className="text-xs text-muted-foreground">
        Autenticação gerenciada inteiramente pelo CLI oficial de cada ferramenta (login via
        navegador/conta) -- o Orquestrador nunca lê, copia ou armazena essas credenciais. Faça
        login normalmente no terminal (ex.: <code className="rounded bg-muted px-1 py-0.5">codex login</code>)
        e clique em "Verificar novamente".
      </p>
    </div>
  );
}
