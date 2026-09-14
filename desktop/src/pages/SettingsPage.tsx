import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BudgetSettings } from "@/components/BudgetSettings";
import { DataManagementSettings } from "@/components/DataManagementSettings";
import packageJson from "../../package.json";

const PLACEHOLDER_SECTIONS = [
  {
    value: "general",
    label: "Geral",
    description: "Preferências gerais do aplicativo.",
    body: "Configurações gerais serão adicionadas conforme o AgentMash evoluir (idioma, diretório de dados, etc). Providers (API e CLI/Subscription) agora têm sua própria página na navegação principal.",
  },
  {
    value: "appearance",
    label: "Aparência",
    description: "Tema e densidade da interface.",
    body: "A interface segue automaticamente o tema claro/escuro do sistema operacional.",
  },
  {
    value: "security",
    label: "Segurança",
    description: "Segredos, permissões e allowlist do bridge.",
    body: "Chaves de API são armazenadas no Keychain (macOS) ou Credential Manager (Windows) via o SecretStore do core, nunca em texto puro, nunca em log e nunca reenviadas ao frontend depois de salvas. Toda operação de arquivo/git/terminal passa por um Permission Engine com risco (baixo/médio/alto/crítico): ações de alto risco (excluir arquivo, git push, reset --hard) exigem confirmação explícita e nenhum agente executa comandos de shell livres.",
  },
];

export function SettingsPage() {
  return (
    <div className="mx-auto w-full max-w-3xl">
      <Tabs defaultValue="general">
        <TabsList className="flex-wrap">
          <TabsTrigger value="general">Geral</TabsTrigger>
          <TabsTrigger value="appearance">Aparência</TabsTrigger>
          <TabsTrigger value="security">Segurança</TabsTrigger>
          <TabsTrigger value="executions">Execuções</TabsTrigger>
          <TabsTrigger value="data">Dados</TabsTrigger>
          <TabsTrigger value="about">Sobre</TabsTrigger>
        </TabsList>

        <TabsContent value="executions">
          <Card>
            <CardHeader>
              <CardTitle>Execuções</CardTitle>
              <CardDescription>
                Limites de custo e política de retry/timeout aplicados a cada execução.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <BudgetSettings />
              <p className="text-xs text-muted-foreground">
                Política de retry atual: até 3 tentativas com backoff exponencial, timeout de 30s
                por chamada de provider, e circuit breaker por provider após 5 falhas consecutivas.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {PLACEHOLDER_SECTIONS.map((section) => (
          <TabsContent key={section.value} value={section.value}>
            <Card>
              <CardHeader>
                <CardTitle>{section.label}</CardTitle>
                <CardDescription>{section.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{section.body}</p>
              </CardContent>
            </Card>
          </TabsContent>
        ))}

        <TabsContent value="data">
          <Card>
            <CardHeader>
              <CardTitle>Dados</CardTitle>
              <CardDescription>
                Backup, restauração e exportação dos dados locais do Orquestrador (banco de dados,
                configurações, playbooks, prompts, regras aprendidas e memória de projeto).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <DataManagementSettings />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="about">
          <Card>
            <CardHeader>
              <CardTitle>Sobre o Orquestrador</CardTitle>
              <CardDescription>Aplicativo desktop local-first para orquestração de múltiplas IAs.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-1 text-sm text-muted-foreground">
              <p>Versão: {packageJson.version}</p>
              <p>Plataforma: {navigator.platform || "desconhecida"}</p>
              <p className="mt-2 text-xs">
                Dados locais permanecem no seu computador. Apenas o texto explicitamente enviado a
                um provider de IA configurado (Claude, Gemini ou OpenAI) sai da máquina -- nunca
                chaves de API, nunca arquivos não relacionados à tarefa em execução.
              </p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
