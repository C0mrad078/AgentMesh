import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProvidersSettings } from "@/components/ProvidersSettings";
import { CliProvidersSettings } from "@/components/CliProvidersSettings";

/**
 * AgentMash V2 (docs/agentmash-v2-migration.md): promotes Providers from a
 * buried Settings tab to its own top-level nav destination, matching the
 * brief's IA (`Office Projects Team Tasks Memory Providers Settings`).
 * `ProvidersSettings`/`CliProvidersSettings` are real, functional
 * credential/config forms (not V1 dashboard chrome) -- reused as-is.
 */
export function ProvidersPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Providers (API)</CardTitle>
          <CardDescription>
            Configure as chaves de API do Claude, Gemini e OpenAI. O AgentMash só usa um provider
            automaticamente depois que ele está conectado aqui.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ProvidersSettings />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Providers (CLI / Subscription)</CardTitle>
          <CardDescription>
            Codex CLI e Claude Code CLI usam a autenticação oficial de cada ferramenta (conta
            ChatGPT/Claude), não uma API key -- e têm acesso próprio a arquivos/terminal, fora do
            sandbox padrão do AgentMash.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CliProvidersSettings />
        </CardContent>
      </Card>
    </div>
  );
}
