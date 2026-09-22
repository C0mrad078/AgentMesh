import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Activity, ArrowRight, CheckCircle2, Circle, KeyRound, Plus, RefreshCw, Rocket, Settings2, Terminal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { modelsApi, providerCliApi, providersApi, runtimeBindingsApi, type RuntimeBinding } from '@/services/api';
import type { Agent, CliProviderName, CliProviderStatus, ModelInfo, ProviderInfo, Project } from '@/types';
import { missionsApi } from '@/missions/api';
import type { Mission } from '@/missions/types';
import { useAgentsStore } from '@/stores/agentsStore';
import { useProjectsStore } from '@/stores/projectsStore';
import { useReliabilityStore } from '@/stores/reliabilityStore';
import { useUiStore } from '@/stores/uiStore';
import type { DiagnosticsProviderDTO } from '@/types/reliability';

const CLI_NAMES: Record<CliProviderName, string> = { codex_cli: 'Codex CLI', claude_code_cli: 'Claude Code CLI', gemini_cli: 'Gemini CLI' };
const ID_COMMAND = () => globalThis.crypto?.randomUUID?.() ?? `onboarding-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const errorText = (error: unknown) => error instanceof Error ? error.message.replace(/(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{8,}/g, '[redacted]').replace(/Bearer\s+\S+/gi, 'Bearer [redacted]').slice(0, 400) : 'Falha sem mensagem detalhada.';
type CliEntry = { key: string; name: string; state: string; version?: string | null; auth?: string | null; source: string };

function Checklist({ done, children }: { done: boolean; children: string }) { const Icon = done ? CheckCircle2 : Circle; return <li className="flex items-center gap-2 text-sm"><Icon aria-hidden="true" className={`size-4 ${done ? 'text-green-600' : 'text-muted-foreground'}`} />{children}</li>; }

export function OnboardingPage() {
  const projectsStore = useProjectsStore();
  const agentsStore = useAgentsStore();
  const reliability = useReliabilityStore();
  const loadProjects = projectsStore.loadProjects;
  const loadAgents = agentsStore.loadAgents;
  const refreshReliability = reliability.refresh;
  const setActivePage = useUiStore(state => state.setActivePage);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [cli, setCli] = useState<Partial<Record<CliProviderName, CliProviderStatus>>>({});
  const [bindings, setBindings] = useState<RuntimeBinding[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loadErrors, setLoadErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [workspacePath, setWorkspacePath] = useState('');
  const [bindingProvider, setBindingProvider] = useState('codex_cli');
  const [bindingLabel, setBindingLabel] = useState('');
  const [newAgentName, setNewAgentName] = useState('');
  const [newAgentRole, setNewAgentRole] = useState('');
  const [agentBinding, setAgentBinding] = useState<Record<string, string>>({});
  const [missionRequest, setMissionRequest] = useState('');
  const [missionCreated, setMissionCreated] = useState<Mission | null>(null);
  const [missionStarted, setMissionStarted] = useState(false);
  const selectedProject: Project | null = projectsStore.projects.find(item => item.id === projectsStore.selectedProjectId) ?? null;

  const loadDependencies = useCallback(async () => {
    setLoadErrors({});
    const outcomes = await Promise.allSettled([
      loadProjects(), loadAgents(), refreshReliability(),
      providersApi.list(), providerCliApi.listStatuses(), runtimeBindingsApi.list(), modelsApi.list(),
    ]);
    const [,, , providersResult, cliResult, bindingsResult, modelsResult] = outcomes;
    const errors: Record<string, string> = {};
    if (providersResult.status === 'fulfilled') setProviders(providersResult.value); else errors.providers = errorText(providersResult.reason);
    if (cliResult.status === 'fulfilled') setCli(cliResult.value); else errors.cli = errorText(cliResult.reason);
    if (bindingsResult.status === 'fulfilled') setBindings(bindingsResult.value); else errors.bindings = errorText(bindingsResult.reason);
    if (modelsResult.status === 'fulfilled') setModels(modelsResult.value); else errors.models = errorText(modelsResult.reason);
    setLoadErrors(errors);
  }, [loadProjects, loadAgents, refreshReliability]);
  useEffect(() => { void loadDependencies(); }, [loadDependencies]);

  const reportedProviders = reliability.diagnostics?.providers;
  const diagnosticProviders = useMemo(() => reportedProviders ?? [], [reportedProviders]);
  const cliRows: CliEntry[] = useMemo(() => {
    const known: CliEntry[] = Object.entries(cli).map(([key, value]) => ({ key, name: CLI_NAMES[key as CliProviderName] ?? key, state: value?.state ?? 'unknown', version: value?.version ?? null, auth: value?.auth_method ?? null, source: 'provider CLI status' }));
    const requested = ['antigravity', 'gh', 'git'];
    for (const name of requested) {
      const reported: DiagnosticsProviderDTO | undefined = diagnosticProviders.find(provider => provider.name.toLowerCase() === name);
      known.push({ key: name, name: name === 'gh' ? 'GitHub CLI (gh)' : name === 'git' ? 'Git' : 'Antigravity', state: reported ? (reported.available ? 'available' : 'not_available') : 'not_reported', version: reported?.version ?? null, source: reported ? 'diagnostics report' : 'status não definido pela API atual' });
    }
    return known;
  }, [cli, diagnosticProviders]);
  const connectedApiProvider = providers.some(provider => provider.connected && provider.enabled);
  const connectedCli = Object.values(cli).some(status => status?.state === 'connected');
  const activeBindings = bindings.filter(binding => binding.enabled);
  const anyAgentForProject = agentsStore.agents.some(agent => agent.project_id === selectedProject?.id);
  const readiness = selectedProject && (connectedApiProvider || connectedCli) && activeBindings.length > 0 && anyAgentForProject;

  async function createProject(event: FormEvent) {
    event.preventDefault(); if (!projectName.trim()) return;
    setBusy('project'); setLoadErrors(current => ({ ...current, action: '' }));
    try { await projectsStore.createProject({ name: projectName.trim(), description: projectDescription.trim(), ...(workspacePath.trim() ? { workspace_path: workspacePath.trim() } : {}) }); setProjectName(''); setProjectDescription(''); setWorkspacePath(''); }
    catch (error) { setLoadErrors(current => ({ ...current, action: errorText(error) })); }
    finally { setBusy(null); }
  }

  async function createBinding(event: FormEvent) {
    event.preventDefault(); if (!bindingProvider || !bindingLabel.trim()) return;
    setBusy('binding'); setLoadErrors(current => ({ ...current, action: '' }));
    try { const created = await runtimeBindingsApi.create({ provider_id: bindingProvider, label: bindingLabel.trim(), configured_capacity: 1 }); setBindings(current => [...current, created]); setBindingLabel(''); }
    catch (error) { setLoadErrors(current => ({ ...current, action: errorText(error) })); }
    finally { setBusy(null); }
  }

  async function createAgent(event: FormEvent) {
    event.preventDefault(); if (!selectedProject || !newAgentName.trim()) return;
    setBusy('agent'); setLoadErrors(current => ({ ...current, action: '' }));
    try { await agentsStore.createAgent({ name: newAgentName.trim(), role: newAgentRole.trim() || undefined, project_id: selectedProject.id, runtime_binding_id: activeBindings[0]?.id ?? null }); setNewAgentName(''); setNewAgentRole(''); }
    catch (error) { setLoadErrors(current => ({ ...current, action: errorText(error) })); }
    finally { setBusy(null); }
  }

  async function saveAgentBinding(agent: Agent) {
    const bindingId = agentBinding[agent.id]; if (!selectedProject || !bindingId) return;
    setBusy(`agent-${agent.id}`); setLoadErrors(current => ({ ...current, action: '' }));
    try { await agentsStore.updateAgent(agent.id, { project_id: selectedProject.id, runtime_binding_id: bindingId }); }
    catch (error) { setLoadErrors(current => ({ ...current, action: errorText(error) })); }
    finally { setBusy(null); }
  }

  async function startFirstMission(event: FormEvent) {
    event.preventDefault(); if (!selectedProject || !missionRequest.trim()) return;
    setBusy('mission'); setMissionCreated(null); setMissionStarted(false); setLoadErrors(current => ({ ...current, action: '' }));
    try {
      const mission = await missionsApi.create(selectedProject.id, missionRequest.trim(), ID_COMMAND());
      setMissionCreated(mission);
      const started = await missionsApi.command(mission.id, { action: 'analyze' }, ID_COMMAND());
      setMissionCreated(started);
      setMissionStarted(true);
    } catch (error) { setLoadErrors(current => ({ ...current, action: errorText(error) })); }
    finally { setBusy(null); }
  }

  const diagnosticsErrorText = reliability.errors.diagnostics?.toLowerCase() ?? '';
  const globalWarnings = [
    selectedProject && !connectedApiProvider && !connectedCli ? 'Nenhum provider autenticado/conectado foi confirmado.' : null,
    activeBindings.some(binding => /quota|rate.?limit|exhaust/i.test(binding.health) || Boolean(binding.backoff_until && new Date(binding.backoff_until).valueOf() > Date.now())) ? 'Há quota limitada ou backoff ativo em pelo menos um runtime binding.' : null,
    /locked|busy database/.test(diagnosticsErrorText) ? 'O banco reportou lock/busy; aguarde ou feche outra instância antes de operações de escrita.' : null,
    /migration|schema incompatible/.test(diagnosticsErrorText) ? 'A verificação indicou possível incompatibilidade de migration/schema.' : null,
  ].filter((item): item is string => Boolean(item));

  return <main className="mx-auto flex w-full max-w-5xl flex-col gap-5 pb-8" aria-labelledby="onboarding-title">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Primeiro uso</p><h1 id="onboarding-title" className="text-2xl font-bold">Bem-vindo ao AgentMash</h1><p className="text-sm text-muted-foreground">Configure um projeto e confirme as capacidades antes da primeira missão.</p></div><Button variant="outline" disabled={busy !== null} onClick={() => void loadDependencies()}><RefreshCw aria-hidden="true" className="size-4" />Atualizar detecção</Button></header>
    {busy && <p role="status" aria-live="polite">Operação em andamento: {busy}…</p>}
    {projectsStore.loading && <p role="status">Carregando projetos…</p>}
    {loadErrors.action && <p role="alert" className="rounded-md border border-destructive p-3 text-sm">{loadErrors.action}</p>}
    {loadErrors.providers && <p role="alert" className="rounded-md border border-destructive p-3 text-sm">Não foi possível consultar providers: {loadErrors.providers}</p>}
    {projectsStore.error && <p role="alert" className="rounded-md border border-destructive p-3 text-sm">Não foi possível carregar projetos: {projectsStore.error}</p>}

    <Card><CardHeader><CardTitle>1. Projeto</CardTitle><CardDescription>Escolha um projeto existente ou crie um. Diretório só é necessário para executar trabalho local.</CardDescription></CardHeader><CardContent className="space-y-4">
      {projectsStore.projects.length ? <div className="flex flex-col gap-1.5"><label htmlFor="onboarding-project" className="text-sm font-medium">Projeto selecionado</label><select id="onboarding-project" className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={projectsStore.selectedProjectId ?? ''} onChange={event => projectsStore.selectProject(event.target.value || null)}><option value="">Selecione…</option>{projectsStore.projects.map(project => <option key={project.id} value={project.id}>{project.name}{project.status === 'archived' ? ' (arquivado)' : ''}</option>)}</select>{selectedProject && <p className="text-xs text-muted-foreground">{selectedProject.workspace_path ? `Workspace: ${selectedProject.workspace_path}` : 'Workspace não configurado.'}</p>}</div> : <p className="rounded border border-dashed border-border p-3 text-sm text-muted-foreground">Primeiro uso: nenhum projeto cadastrado.</p>}
      <form className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2" onSubmit={event => void createProject(event)}><h2 className="text-sm font-semibold sm:col-span-2">Criar projeto</h2><label className="grid gap-1 text-xs">Nome<input className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={projectName} onChange={event => setProjectName(event.target.value)} required /></label><label className="grid gap-1 text-xs">Diretório de workspace (opcional)<input className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={workspacePath} onChange={event => setWorkspacePath(event.target.value)} placeholder="Caminho local" /></label><label className="grid gap-1 text-xs sm:col-span-2">Descrição<textarea className="min-h-16 rounded-md border border-input bg-background px-3 py-2 text-sm" value={projectDescription} onChange={event => setProjectDescription(event.target.value)} /></label><Button type="submit" disabled={busy !== null || !projectName.trim()} className="sm:col-span-2"><Plus aria-hidden="true" className="size-4" />{busy === 'project' ? 'Criando…' : 'Criar e selecionar projeto'}</Button></form>
    </CardContent></Card>

    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Terminal aria-hidden="true" className="size-4" />2. CLIs e autenticação</CardTitle><CardDescription>Detecção baseada nos status reais. Este assistente não coleta nem armazena credenciais.</CardDescription></CardHeader><CardContent className="space-y-4">
      <ul className="grid gap-2 sm:grid-cols-2">{cliRows.map(row => <li key={row.key} className="flex items-center justify-between gap-3 rounded border border-border p-3"><div><p className="text-sm font-medium">{row.name}</p><p className="text-xs text-muted-foreground">{row.version ? `Versão ${row.version} · ` : ''}{row.source}</p></div><span className={`rounded-full px-2 py-1 text-xs ${['connected', 'available'].includes(row.state) ? 'bg-green-600/10 text-green-700' : row.state === 'not_installed' || row.state === 'not_available' ? 'bg-amber-600/10 text-amber-700' : 'bg-muted text-muted-foreground'}`}>{row.state === 'connected' ? `autenticado${row.auth ? ` (${row.auth})` : ''}` : row.state === 'available' ? 'disponível' : row.state === 'not_installed' || row.state === 'not_available' ? 'ausente' : 'não reportado'}</span></li>)}</ul>
      {loadErrors.cli && <p role="alert" className="text-sm text-destructive">Falha ao detectar CLIs: {loadErrors.cli}</p>}
      <div><h2 className="mb-2 text-sm font-semibold">Providers API</h2>{providers.length ? <ul className="flex flex-wrap gap-2">{providers.map(provider => <li key={provider.provider} className="rounded border border-border px-3 py-2 text-xs">{provider.display_name}: {provider.connected && provider.enabled ? 'conectado' : provider.enabled ? 'configurado, conexão não confirmada' : 'não autenticado'}</li>)}</ul> : <p className="text-xs text-muted-foreground">Status de autenticação indisponível ou nenhum provider configurado.</p>}<Button className="mt-3" size="sm" variant="outline" onClick={() => setActivePage('providers')}><KeyRound aria-hidden="true" className="size-4" />Abrir configuração de autenticação</Button></div>
      {reliability.errors.onboarding && <p role="alert" className="text-xs text-muted-foreground">Status detalhado do onboarding indisponível: {reliability.errors.onboarding}. Os indicadores acima vêm das APIs conhecidas do app.</p>}
    </CardContent></Card>

    <Card><CardHeader><CardTitle>3. RuntimeBindings e capacidade</CardTitle><CardDescription>Bindings e capacidade vêm do backend; não há quotas presumidas quando o backend não as informa.</CardDescription></CardHeader><CardContent className="space-y-3">
      {!bindings.length ? <p className="rounded border border-dashed border-border p-3 text-sm text-muted-foreground">Nenhum RuntimeBinding encontrado.</p> : <ul className="space-y-2">{bindings.map(binding => { const remaining = binding.observed_capacity - binding.reserved_slots; const isLimited = /quota|rate.?limit|exhaust/i.test(binding.health) || Boolean(binding.backoff_until && new Date(binding.backoff_until).valueOf() > Date.now()); return <li key={binding.id} className="flex flex-wrap items-center justify-between gap-3 rounded border border-border p-3"><div><p className="text-sm font-medium">{binding.label} · {binding.provider_id}</p><p className="text-xs text-muted-foreground">Saúde: {binding.health} · capacidade observada/configurada: {binding.observed_capacity}/{binding.configured_capacity} · slots reservados: {binding.reserved_slots}</p>{binding.backoff_until && <p className="text-xs text-muted-foreground">Backoff até {binding.backoff_until}</p>}</div><span className="text-xs">{!binding.enabled ? 'desabilitado' : isLimited ? 'quota/backoff informado' : Number.isFinite(remaining) ? `${Math.max(0, remaining)} slot(s) livres observados` : 'capacidade não informada'}</span></li>; })}</ul>}
      {loadErrors.bindings && <p role="alert" className="text-sm text-destructive">Falha ao carregar bindings: {loadErrors.bindings}</p>}
      <form className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onSubmit={event => void createBinding(event)}><label className="grid gap-1 text-xs">Provider ID<select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={bindingProvider} onChange={event => setBindingProvider(event.target.value)}><option value="codex_cli">codex_cli</option><option value="claude_code_cli">claude_code_cli</option><option value="gemini_cli">gemini_cli</option><option value="antigravity">antigravity</option></select></label><label className="grid gap-1 text-xs">Rótulo<input className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={bindingLabel} onChange={event => setBindingLabel(event.target.value)} placeholder="Ex.: Codex principal" required /></label><Button type="submit" disabled={busy !== null || !bindingLabel.trim()}><Plus aria-hidden="true" className="size-4" />{busy === 'binding' ? 'Criando…' : 'Criar binding'}</Button></form>
      <Button size="sm" variant="outline" onClick={() => setActivePage('runtime-bindings')}><Settings2 aria-hidden="true" className="size-4" />Gerenciar todos os bindings</Button>
    </CardContent></Card>

    <Card><CardHeader><CardTitle>4. Agentes e modelos</CardTitle><CardDescription>Associe agentes ao projeto e aos bindings ativos. Capacidades não informadas ficam como não disponíveis.</CardDescription></CardHeader><CardContent className="space-y-4">
      {!selectedProject ? <p className="text-sm text-muted-foreground">Selecione ou crie um projeto antes de configurar agentes.</p> : <>
        {models.length > 0 && <p className="text-xs text-muted-foreground">{models.length} modelo(s) retornados pelo backend: {models.slice(0, 4).map(model => model.display_name).join(', ')}{models.length > 4 ? '…' : ''}</p>}
        {agentsStore.agents.filter(agent => agent.project_id === selectedProject.id).map(agent => <div key={agent.id} className="flex flex-wrap items-center gap-2 rounded border border-border p-3"><span className="min-w-32 flex-1 text-sm">{agent.name} · {agent.role || agent.provider}</span><label className="flex items-center gap-2 text-xs">RuntimeBinding<select aria-label={`RuntimeBinding de ${agent.name}`} className="h-9 rounded-md border border-input bg-background px-3 text-xs" value={agentBinding[agent.id] ?? agent.runtime_binding_id ?? ''} onChange={event => setAgentBinding(current => ({ ...current, [agent.id]: event.target.value }))}><option value="">Selecione…</option>{activeBindings.map(binding => <option key={binding.id} value={binding.id}>{binding.label} · {binding.health}</option>)}</select></label><Button size="sm" variant="outline" disabled={busy !== null || !(agentBinding[agent.id] ?? agent.runtime_binding_id)} onClick={() => void saveAgentBinding(agent)}>{busy === `agent-${agent.id}` ? 'Salvando…' : 'Salvar vínculo'}</Button></div>)}
        {!agentsStore.agents.some(agent => agent.project_id === selectedProject.id) && <p className="text-sm text-muted-foreground">Nenhum agente associado a este projeto.</p>}
        <form className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2" onSubmit={event => void createAgent(event)}><h2 className="text-sm font-semibold sm:col-span-2">Criar agente</h2><label className="grid gap-1 text-xs">Nome<input className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={newAgentName} onChange={event => setNewAgentName(event.target.value)} required /></label><label className="grid gap-1 text-xs">Papel opcional<input className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={newAgentRole} onChange={event => setNewAgentRole(event.target.value)} /></label><Button type="submit" disabled={busy !== null || !newAgentName.trim()} className="sm:col-span-2"><Plus aria-hidden="true" className="size-4" />{busy === 'agent' ? 'Criando…' : 'Criar agente neste projeto'}</Button></form>
      </>}
    </CardContent></Card>

    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Rocket aria-hidden="true" className="size-4" />5. Primeira missão</CardTitle><CardDescription>A missão só será marcada como iniciada depois que o backend confirmar criação e análise.</CardDescription></CardHeader><CardContent className="space-y-3">
      <form className="space-y-3" onSubmit={event => void startFirstMission(event)}><label htmlFor="first-mission-request" className="text-sm font-medium">O que você quer realizar?</label><Textarea id="first-mission-request" value={missionRequest} onChange={event => setMissionRequest(event.target.value)} rows={4} placeholder="Descreva o objetivo da primeira missão" required /><Button type="submit" disabled={!selectedProject || !missionRequest.trim() || busy !== null || !connectedApiProvider && !connectedCli}><Activity aria-hidden="true" className="size-4" />{busy === 'mission' ? 'Enviando para análise…' : 'Criar e iniciar missão'}</Button>{!selectedProject && <p className="text-xs text-muted-foreground">Selecione um projeto primeiro.</p>}{selectedProject && !connectedApiProvider && !connectedCli && <p className="text-xs text-amber-700">Conecte um provider antes de iniciar uma missão.</p>}</form>
      {missionCreated && <div className={`rounded border p-3 text-sm ${missionStarted ? 'border-green-600/40' : 'border-amber-600/40'}`} role={missionStarted ? 'status' : 'alert'}><p className="font-semibold">{missionStarted ? 'Primeira missão enviada para análise pelo backend.' : 'Missão criada, início/análise não confirmado.'}</p><p>ID {missionCreated.id} · estado reportado: {missionCreated.status}</p></div>}
      {loadErrors.models && <p className="text-xs text-muted-foreground">Modelos indisponíveis: {loadErrors.models}</p>}
    </CardContent></Card>

    <Card><CardHeader><CardTitle>Estado global e prontidão</CardTitle><CardDescription>Checklist construído apenas a partir dos dados observados nesta sessão.</CardDescription></CardHeader><CardContent className="space-y-3"><ul className="space-y-2"><Checklist done={projectsStore.loaded}>Projetos consultados</Checklist><Checklist done={selectedProject !== null}>Projeto selecionado</Checklist><Checklist done={connectedApiProvider || connectedCli}>Pelo menos um provider/CLI com conexão confirmada</Checklist><Checklist done={activeBindings.length > 0}>RuntimeBinding habilitado</Checklist><Checklist done={anyAgentForProject}>Agente associado ao projeto</Checklist><Checklist done={reliability.diagnostics !== null && !reliability.errors.diagnostics}>Diagnóstico local carregado</Checklist></ul>
      {globalWarnings.map(warning => <p key={warning} role="status" className="rounded border border-amber-600/30 bg-amber-600/5 p-2 text-xs">{warning}</p>)}
      {readiness ? <p className="flex items-center gap-2 rounded border border-green-600/40 bg-green-600/5 p-3 text-sm" role="status"><CheckCircle2 aria-hidden="true" className="size-4 text-green-600" />Capacidade mínima observada; onboarding pode ser concluído.</p> : <p className="flex items-center gap-2 rounded border border-border p-3 text-sm text-muted-foreground" role="status"><ArrowRight aria-hidden="true" className="size-4" />Conclua os itens pendentes para alcançar estado pronto.</p>}
    </CardContent></Card>
  </main>;
}
