import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProvidersSettings } from "@/components/ProvidersSettings";
import { BudgetSettings } from "@/components/BudgetSettings";

const PLACEHOLDER_SECTIONS = [
  {
    value: "general",
    label: "Geral",
    description: "Preferências gerais do aplicativo.",
    body: "Configurações gerais serão adicionadas conforme o Orquestrador evoluir (idioma, diretório de dados, etc).",
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
    body: "Chaves de API são armazenadas no Keychain (macOS) ou Credential Manager (Windows) via o SecretStore do core, nunca em texto puro, nunca em log e nunca reenviadas ao frontend depois de salvas. Toda operação de arquivo/git/terminal passa por uma allowlist tipada — nenhum agente executa comandos livres.",
  },
  {
    value: "learning",
    label: "Aprendizado",
    description: "Como o Orquestrador aprende com execuções passadas.",
    body: "O sistema de aprendizado (Reflection Engine, regras aprendidas, evolução de prompts) será implementado em um estágio futuro. Os dados necessários (custos, tempos, taxa de sucesso, decisões de roteamento) já estão sendo capturados desde agora.",
  },
];

export function SettingsPage() {
  return (
    <div className="mx-auto w-full max-w-3xl">
      <Tabs defaultValue="providers">
        <TabsList className="flex-wrap">
          <TabsTrigger value="general">Geral</TabsTrigger>
          <TabsTrigger value="appearance">Aparência</TabsTrigger>
          <TabsTrigger value="providers">Providers</TabsTrigger>
          <TabsTrigger value="security">Segurança</TabsTrigger>
          <TabsTrigger value="executions">Execuções</TabsTrigger>
          <TabsTrigger value="learning">Aprendizado</TabsTrigger>
        </TabsList>

        <TabsContent value="providers">
          <Card>
            <CardHeader>
              <CardTitle>Providers</CardTitle>
              <CardDescription>
                Configure as chaves de API do Claude, Gemini e OpenAI/Codex. O Orquestrador só
                usa um provider automaticamente depois que ele está conectado aqui.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ProvidersSettings />
            </CardContent>
          </Card>
        </TabsContent>

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
      </Tabs>
    </div>
  );
}
