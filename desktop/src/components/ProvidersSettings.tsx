import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { providersApi } from "@/services/api";
import type { ConnectionTestResult, ProviderInfo, ProviderName } from "@/types";

const TEST_RESULT_LABEL: Record<ConnectionTestResult, string> = {
  connected: "Conectado",
  invalid_key: "Chave inválida",
  timeout: "Tempo esgotado",
  rate_limited: "Limite de requisições atingido",
  provider_unavailable: "Provider indisponível",
  unknown_error: "Erro desconhecido",
};

const HEALTH_LABEL: Record<string, string> = {
  online: "Online",
  degraded: "Degradado",
  rate_limited: "Rate limited",
  unavailable: "Indisponível",
  unknown: "Desconhecido",
};

interface ProviderRowState {
  apiKeyDraft: string;
  saving: boolean;
  testing: boolean;
  testResult: ConnectionTestResult | null;
  error: string | null;
}

function emptyRowState(): ProviderRowState {
  return { apiKeyDraft: "", saving: false, testing: false, testResult: null, error: null };
}

export function ProvidersSettings() {
  const [providers, setProviders] = useState<ProviderInfo[] | null>(null);
  const [rowState, setRowState] = useState<Record<string, ProviderRowState>>({});

  async function reload() {
    const list = await providersApi.list();
    setProviders(list);
  }

  useEffect(() => {
    void reload();
  }, []);

  function updateRow(provider: string, patch: Partial<ProviderRowState>) {
    setRowState((prev) => ({ ...prev, [provider]: { ...(prev[provider] ?? emptyRowState()), ...patch } }));
  }

  async function handleSave(provider: ProviderName) {
    const draft = rowState[provider]?.apiKeyDraft?.trim();
    if (!draft) return;
    updateRow(provider, { saving: true, error: null });
    try {
      await providersApi.setCredential(provider, draft);
      updateRow(provider, { apiKeyDraft: "", saving: false, testResult: null });
      await reload();
    } catch (err) {
      updateRow(provider, { saving: false, error: err instanceof Error ? err.message : String(err) });
    }
  }

  async function handleTest(provider: ProviderName) {
    const draft = rowState[provider]?.apiKeyDraft?.trim();
    updateRow(provider, { testing: true, error: null, testResult: null });
    try {
      const { result } = await providersApi.testConnection(provider, draft || undefined);
      updateRow(provider, { testing: false, testResult: result });
    } catch (err) {
      updateRow(provider, { testing: false, error: err instanceof Error ? err.message : String(err) });
    }
  }

  async function handleRemove(provider: ProviderName) {
    updateRow(provider, { saving: true, error: null });
    try {
      await providersApi.removeCredential(provider);
      updateRow(provider, { saving: false, testResult: null });
      await reload();
    } catch (err) {
      updateRow(provider, { saving: false, error: err instanceof Error ? err.message : String(err) });
    }
  }

  if (providers === null) {
    return <Loader2 className="size-5 animate-spin text-muted-foreground" />;
  }

  return (
    <div className="flex flex-col gap-3">
      {providers.map((provider) => {
        const state = rowState[provider.provider] ?? emptyRowState();
        return (
          <Card key={provider.provider}>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle>{provider.display_name}</CardTitle>
                <CardDescription>
                  {provider.connected ? (
                    <span className="inline-flex items-center gap-1 text-success">
                      <CheckCircle2 className="size-3.5" /> Conectado · {HEALTH_LABEL[provider.health]}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-muted-foreground">
                      <XCircle className="size-3.5" /> Não configurado
                    </span>
                  )}
                </CardDescription>
              </div>
              {provider.connected && (
                <Badge variant={provider.health === "online" ? "success" : "warning"}>
                  {HEALTH_LABEL[provider.health]}
                </Badge>
              )}
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <Label htmlFor={`key-${provider.provider}`} className="mb-1.5 block text-xs">
                    API Key
                  </Label>
                  <Input
                    id={`key-${provider.provider}`}
                    type="password"
                    placeholder={provider.connected ? "•••••••••••••••• (definida)" : "Cole a chave de API"}
                    value={state.apiKeyDraft}
                    onChange={(e) => updateRow(provider.provider, { apiKeyDraft: e.target.value, testResult: null })}
                  />
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={state.testing}
                  onClick={() => void handleTest(provider.provider as ProviderName)}
                >
                  {state.testing ? <Loader2 className="size-4 animate-spin" /> : "Testar conexão"}
                </Button>
                <Button
                  size="sm"
                  disabled={state.saving || !state.apiKeyDraft.trim()}
                  onClick={() => void handleSave(provider.provider as ProviderName)}
                >
                  Salvar
                </Button>
                {provider.connected && (
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={state.saving}
                    onClick={() => void handleRemove(provider.provider as ProviderName)}
                  >
                    Remover
                  </Button>
                )}
              </div>
              {state.testResult && (
                <p className={state.testResult === "connected" ? "text-xs text-success" : "text-xs text-destructive"}>
                  {TEST_RESULT_LABEL[state.testResult]}
                </p>
              )}
              {state.error && <p className="text-xs text-destructive">{state.error}</p>}
            </CardContent>
          </Card>
        );
      })}
      <p className="text-xs text-muted-foreground">
        As chaves são armazenadas no Keychain (macOS) ou Credential Manager (Windows) e nunca
        aparecem novamente na interface depois de salvas.
      </p>
    </div>
  );
}
