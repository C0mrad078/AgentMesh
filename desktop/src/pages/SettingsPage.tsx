import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const SECTIONS = [
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
    value: "providers",
    label: "Providers",
    description: "Conexões com provedores de IA.",
    body: "Neste estágio apenas o MockProvider está disponível. Claude, Gemini e OpenAI/Codex serão adicionados no próximo estágio.",
  },
  {
    value: "security",
    label: "Segurança",
    description: "Segredos, permissões e allowlist do bridge.",
    body: "Chaves de API serão armazenadas no Keychain (macOS) ou Credential Manager (Windows) via o SecretStore do core, nunca em texto puro.",
  },
  {
    value: "executions",
    label: "Execuções",
    description: "Políticas de timeout, retry e concorrência.",
    body: "Os valores padrão atuais são: 3 tentativas, backoff exponencial e timeout de 10s por etapa.",
  },
  {
    value: "learning",
    label: "Aprendizado",
    description: "Como o Orquestrador aprende com execuções passadas.",
    body: "O sistema de aprendizado será implementado em um estágio futuro.",
  },
];

export function SettingsPage() {
  return (
    <div className="mx-auto w-full max-w-3xl">
      <Tabs defaultValue="general">
        <TabsList className="flex-wrap">
          {SECTIONS.map((section) => (
            <TabsTrigger key={section.value} value={section.value}>
              {section.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {SECTIONS.map((section) => (
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
