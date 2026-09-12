import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  agentsApi,
  contextOptimizerApi,
  learningApi,
  modelPerformanceApi,
  playbooksApi,
  promptsApi,
} from "@/services/api";
import type {
  Agent,
  ContextSuggestion,
  LearnedRule,
  LearningCandidate,
  LearningMode,
  LearningPolicy,
  ModelPerformanceSummary,
  Playbook,
  PlaybookVersion,
  PromptProposalEvent,
  PromptVersion,
  RuleStatus,
} from "@/types";

const STATUS_LABEL: Record<RuleStatus, string> = {
  candidate: "Candidata",
  observing: "Em observação",
  active: "Ativa",
  deprecated: "Descontinuada",
  rejected: "Rejeitada",
  archived: "Arquivada",
};

const STATUS_VARIANT: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  active: "success",
  observing: "warning",
  candidate: "secondary",
  promoted: "success",
  deprecated: "destructive",
  rejected: "destructive",
  archived: "secondary",
};

const OWNER_KEYS = ["core", "planner", "router", "verifier", "reflection", "synthesizer"] as const;

export function LearningPage() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Aprendizado do Orquestrador</h2>
        <p className="text-xs text-muted-foreground">
          Regras, candidatos, playbooks, desempenho de modelos e versões de prompts, todos com
          evidência, confiança e possibilidade de reverter.
        </p>
      </div>
      <Tabs defaultValue="overview">
        <TabsList className="flex-wrap">
          <TabsTrigger value="overview">Visão geral</TabsTrigger>
          <TabsTrigger value="rules">Regras</TabsTrigger>
          <TabsTrigger value="candidates">Candidatos</TabsTrigger>
          <TabsTrigger value="playbooks">Playbooks</TabsTrigger>
          <TabsTrigger value="performance">Desempenho</TabsTrigger>
          <TabsTrigger value="prompts">Prompts</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab />
        </TabsContent>
        <TabsContent value="rules">
          <RulesTab />
        </TabsContent>
        <TabsContent value="candidates">
          <CandidatesTab />
        </TabsContent>
        <TabsContent value="playbooks">
          <PlaybooksTab />
        </TabsContent>
        <TabsContent value="performance">
          <PerformanceTab />
        </TabsContent>
        <TabsContent value="prompts">
          <PromptsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function OverviewTab() {
  const [policy, setPolicy] = useState<LearningPolicy | null>(null);
  const [rules, setRules] = useState<LearnedRule[] | null>(null);
  const [candidates, setCandidates] = useState<LearningCandidate[] | null>(null);
  const [playbooks, setPlaybooks] = useState<Playbook[] | null>(null);
  const [saving, setSaving] = useState(false);

  async function reload() {
    const [p, r, c, pb] = await Promise.all([
      learningApi.policy(), learningApi.rules(), learningApi.candidates(), playbooksApi.list(),
    ]);
    setPolicy(p);
    setRules(r);
    setCandidates(c);
    setPlaybooks(pb);
  }

  useEffect(() => {
    void reload();
  }, []);

  async function handleModeChange(mode: LearningMode) {
    if (!policy) return;
    setSaving(true);
    try {
      setPolicy(await learningApi.setPolicy({ mode }));
    } finally {
      setSaving(false);
    }
  }

  if (policy === null || rules === null || candidates === null || playbooks === null) {
    return <Loader2 className="size-5 animate-spin text-muted-foreground" />;
  }

  const activeRules = rules.filter((r) => r.status === "active").length;
  const pendingCandidates = candidates.filter((c) => c.status === "candidate" || c.status === "observing").length;

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Regras ativas" value={activeRules} />
        <StatCard label="Candidatos" value={pendingCandidates} />
        <StatCard label="Playbooks" value={playbooks.length} />
        <StatCard label="Modo de aprendizado" value={policy.mode} />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Modo de aprendizado</CardTitle>
          <CardDescription>
            Manual exige aprovação para tudo. Assistido (padrão) aplica automaticamente apenas
            mudanças de baixo risco em playbooks; o resto vira proposta. Autônomo permite mais
            automação, mas nunca em categorias de segurança/verificação.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex gap-2">
          {(["manual", "assisted", "autonomous"] as LearningMode[]).map((mode) => (
            <Button
              key={mode}
              size="sm"
              disabled={saving}
              variant={policy.mode === mode ? "default" : "outline"}
              onClick={() => void handleModeChange(mode)}
            >
              {mode === "manual" ? "Manual" : mode === "assisted" ? "Assistido" : "Autônomo"}
            </Button>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 p-4">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-xl font-semibold">{value}</span>
      </CardContent>
    </Card>
  );
}

function RulesTab() {
  const [rules, setRules] = useState<LearnedRule[] | null>(null);
  const [form, setForm] = useState({ title: "", category: "routing", rule_text: "" });
  const [creating, setCreating] = useState(false);

  async function reload() {
    setRules(await learningApi.rules());
  }

  useEffect(() => {
    void reload();
  }, []);

  async function togglePin(rule: LearnedRule) {
    if (rule.pinned) {
      await learningApi.unpinRule(rule.id);
    } else {
      await learningApi.pinRule(rule.id);
    }
    await reload();
  }

  async function rollback(rule: LearnedRule) {
    await learningApi.rollbackRule(rule.id, "Revertido manualmente pelo usuário.");
    await reload();
  }

  async function createRule() {
    if (!form.title.trim() || !form.rule_text.trim()) return;
    setCreating(true);
    try {
      await learningApi.createRule(form);
      setForm({ title: "", category: "routing", rule_text: "" });
      await reload();
    } finally {
      setCreating(false);
    }
  }

  if (rules === null) return <Loader2 className="size-5 animate-spin text-muted-foreground" />;

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Criar regra manual</CardTitle>
          <CardDescription>
            Regras criadas pelo usuário ficam ativas imediatamente e nunca são alteradas
            automaticamente pelo Learning Engine.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <Input
            placeholder="Título"
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
          />
          <Textarea
            placeholder="Descreva a regra..."
            value={form.rule_text}
            onChange={(e) => setForm((f) => ({ ...f, rule_text: e.target.value }))}
          />
          <Button size="sm" className="self-start" disabled={creating} onClick={() => void createRule()}>
            {creating ? <Loader2 className="size-4 animate-spin" /> : "Criar regra"}
          </Button>
        </CardContent>
      </Card>

      {rules.length === 0 && <p className="text-sm text-muted-foreground">Nenhuma regra ainda.</p>}
      {rules.map((rule) => (
        <Card key={rule.id}>
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle className="text-sm">{rule.title}</CardTitle>
              <CardDescription>{rule.category} · escopo: {rule.scope_type}{rule.scope_value ? `:${rule.scope_value}` : ""}</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {rule.pinned && <Badge variant="outline">fixada</Badge>}
              <Badge variant={STATUS_VARIANT[rule.status]}>{STATUS_LABEL[rule.status]}</Badge>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-xs text-muted-foreground">
            <p>
              Confiança: {(rule.confidence * 100).toFixed(0)}% · {rule.observations} observações ·
              {" "}{rule.successes} sucessos · {rule.failures} falhas · origem: {rule.source}
            </p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => void togglePin(rule)}>
                {rule.pinned ? "Desfixar" : "Fixar"}
              </Button>
              {rule.status === "active" && !rule.pinned && (
                <Button variant="destructive" size="sm" onClick={() => void rollback(rule)}>
                  Reverter
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function CandidatesTab() {
  const [candidates, setCandidates] = useState<LearningCandidate[] | null>(null);

  async function reload() {
    setCandidates(await learningApi.candidates());
  }

  useEffect(() => {
    void reload();
  }, []);

  async function approve(id: string) {
    await learningApi.approveCandidate(id);
    await reload();
  }

  async function reject(id: string) {
    await learningApi.rejectCandidate(id, "Rejeitado manualmente pelo usuário.");
    await reload();
  }

  if (candidates === null) return <Loader2 className="size-5 animate-spin text-muted-foreground" />;
  if (candidates.length === 0) {
    return <p className="text-sm text-muted-foreground">Nenhum candidato de aprendizado ainda.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {candidates.map((candidate) => (
        <Card key={candidate.id}>
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle className="text-sm">{candidate.title}</CardTitle>
              <CardDescription>{candidate.rule_text}</CardDescription>
            </div>
            <Badge variant={STATUS_VARIANT[candidate.status]}>{candidate.status}</Badge>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-xs text-muted-foreground">
            <p>
              Confiança: {(candidate.confidence * 100).toFixed(0)}% · {candidate.observations} observações
              em {candidate.distinct_projects.length} projeto(s)
            </p>
            {(candidate.status === "candidate" || candidate.status === "observing") && (
              <div className="flex gap-2">
                <Button size="sm" onClick={() => void approve(candidate.id)}>Aprovar</Button>
                <Button variant="outline" size="sm" onClick={() => void reject(candidate.id)}>Rejeitar</Button>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function PlaybooksTab() {
  const [playbooks, setPlaybooks] = useState<Playbook[] | null>(null);
  const [versionsByPlaybook, setVersionsByPlaybook] = useState<Record<string, PlaybookVersion[]>>({});
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    void playbooksApi.list().then(setPlaybooks);
  }, []);

  async function toggle(playbook: Playbook) {
    const next = expanded === playbook.id ? null : playbook.id;
    setExpanded(next);
    if (next && !versionsByPlaybook[playbook.id]) {
      const versions = await playbooksApi.versions(playbook.id);
      setVersionsByPlaybook((prev) => ({ ...prev, [playbook.id]: versions }));
    }
  }

  if (playbooks === null) return <Loader2 className="size-5 animate-spin text-muted-foreground" />;

  return (
    <div className="flex flex-col gap-3">
      {playbooks.map((playbook) => (
        <Card key={playbook.id}>
          <button className="flex w-full items-center justify-between p-4 text-left" onClick={() => void toggle(playbook)}>
            <div>
              <p className="text-sm font-medium">{playbook.name}</p>
              <p className="text-xs text-muted-foreground">
                {playbook.task_type} · condições: {playbook.conditions.join(", ") || "nenhuma"}
              </p>
            </div>
            <Badge variant={playbook.status === "active" ? "success" : "secondary"}>{playbook.status}</Badge>
          </button>
          {expanded === playbook.id && (
            <CardContent className="border-t border-border pt-3">
              {(versionsByPlaybook[playbook.id] ?? []).map((version) => (
                <div key={version.id} className="mb-2 text-xs">
                  <p className="font-medium">
                    v{version.version} {version.active && "(ativa)"} · confiança {(version.confidence * 100).toFixed(0)}%
                    {" "}· {version.observations} execuções, {version.successes} sucessos
                  </p>
                  <ol className="ml-4 list-decimal text-muted-foreground">
                    {version.strategy.map((step, i) => (
                      <li key={i}>{step.description} ({step.capability}/{step.step_type})</li>
                    ))}
                  </ol>
                </div>
              ))}
            </CardContent>
          )}
        </Card>
      ))}
    </div>
  );
}

function PerformanceTab() {
  const [summaries, setSummaries] = useState<ModelPerformanceSummary[] | null>(null);
  const [contextSuggestions, setContextSuggestions] = useState<ContextSuggestion[] | null>(null);

  useEffect(() => {
    void modelPerformanceApi.list().then(setSummaries);
    void contextOptimizerApi.suggestions().then(setContextSuggestions);
  }, []);

  if (summaries === null) return <Loader2 className="size-5 animate-spin text-muted-foreground" />;

  return (
    <div className="flex flex-col gap-4">
      {summaries.length === 0 ? (
        <p className="text-sm text-muted-foreground">Ainda não há dados suficientes de execuções.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="p-2">Agente</th>
                <th className="p-2">Modelo</th>
                <th className="p-2">Categoria</th>
                <th className="p-2">Execuções</th>
                <th className="p-2">Sucesso verificado</th>
                <th className="p-2">Retry</th>
                <th className="p-2">Latência média</th>
                <th className="p-2">Custo médio</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map((s, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="p-2">{s.agent_id}</td>
                  <td className="p-2">{s.provider}/{s.model}</td>
                  <td className="p-2">{s.task_category}</td>
                  <td className="p-2">{s.executions}</td>
                  <td className="p-2">{(s.verified_success_rate * 100).toFixed(0)}%</td>
                  <td className="p-2">{(s.retry_rate * 100).toFixed(0)}%</td>
                  <td className="p-2">{s.avg_latency_seconds.toFixed(1)}s</td>
                  <td className="p-2">${s.avg_cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {contextSuggestions && contextSuggestions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Sugestões de contexto</CardTitle>
            <CardDescription>
              Com base em quais arquivos enviados a agentes realmente aparecem no resultado.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {contextSuggestions.map((s, i) => (
              <div key={i} className="text-xs">
                <Badge variant="outline" className="mr-2">{s.task_category}: {s.suggestion}</Badge>
                <span className="text-muted-foreground">{s.detail}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function PromptsTab() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [ownerKey, setOwnerKey] = useState<string>("planner");
  const [versions, setVersions] = useState<PromptVersion[] | null>(null);
  const [diffTarget, setDiffTarget] = useState<PromptVersion | null>(null);
  const [proposals, setProposals] = useState<PromptProposalEvent[] | null>(null);

  useEffect(() => {
    void agentsApi.list().then(setAgents);
    void promptsApi.proposals().then(setProposals);
  }, []);

  useEffect(() => {
    setVersions(null);
    void promptsApi.versions(ownerKey).then(setVersions);
  }, [ownerKey]);

  async function rollback(version: PromptVersion) {
    await promptsApi.rollback(ownerKey, version.id, "Revertido manualmente pelo usuário.");
    setVersions(await promptsApi.versions(ownerKey));
  }

  async function applyProposal(proposal: PromptProposalEvent) {
    await promptsApi.applyProposal(proposal.id);
    setProposals(await promptsApi.proposals());
    if (proposal.evidence.owner_key === ownerKey) {
      setVersions(await promptsApi.versions(ownerKey));
    }
  }

  const allKeys = [...OWNER_KEYS, ...agents.map((a) => a.id)];

  return (
    <div className="flex flex-col gap-3">
      {proposals && proposals.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Propostas pendentes</CardTitle>
            <CardDescription>
              Mudanças de prompt sugeridas por reflexões, aguardando aprovação (categoria "prompt"
              exige aprovação por padrão).
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {proposals.map((proposal) => (
              <div key={proposal.id} className="rounded-md border border-border p-2 text-xs">
                <p className="font-medium">{proposal.evidence.owner_key}</p>
                <p className="text-muted-foreground">{proposal.evidence.reason}</p>
                <Button size="sm" className="mt-1" onClick={() => void applyProposal(proposal)}>
                  Aplicar
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      <div className="flex flex-wrap gap-2">
        {allKeys.map((key) => (
          <button
            key={key}
            onClick={() => setOwnerKey(key)}
            className={`rounded-full border px-3 py-1 text-xs ${
              ownerKey === key ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
            }`}
          >
            {key}
          </button>
        ))}
      </div>
      {versions === null ? (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      ) : (
        <div className="flex flex-col gap-2">
          {versions.map((version) => (
            <Card key={version.id}>
              <CardHeader className="flex-row items-center justify-between space-y-0">
                <CardTitle className="text-sm">
                  v{version.version} {version.active && "(ativa)"} {version.protected && "· protegida"}
                </CardTitle>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => setDiffTarget(diffTarget?.id === version.id ? null : version)}>
                    {diffTarget?.id === version.id ? "Ocultar" : "Ver conteúdo"}
                  </Button>
                  {!version.active && (
                    <Button size="sm" onClick={() => void rollback(version)}>Reverter para esta</Button>
                  )}
                </div>
              </CardHeader>
              <CardContent className="text-xs text-muted-foreground">
                <p>autor: {version.author} · origem: {version.origin} · motivo: {version.reason || "-"}</p>
                {diffTarget?.id === version.id && (
                  <pre className="mt-2 whitespace-pre-wrap rounded-md bg-muted p-2 text-foreground">
                    {version.content}
                  </pre>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        <Label className="mr-1 inline">Nota:</Label>
        o Core Prompt é protegido -- uma nova versão só pode ser criada por uma ação explícita do
        usuário, nunca automaticamente pelo Learning Engine.
      </p>
    </div>
  );
}
