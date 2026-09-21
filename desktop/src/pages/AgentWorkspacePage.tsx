import { useEffect, useMemo, useRef, useState } from 'react';
import { Background, Controls, MiniMap, ReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Button } from '@/components/ui/button';
import { agentsApi, providerCliApi, settingsApi } from '@/services/api';
import { invokeBridge, onBridgeEvent } from '@/services/bridge';
import { useProjectsStore } from '@/stores/projectsStore';
import { useUiStore } from '@/stores/uiStore';
import { useConnectionStore } from '@/stores/connectionStore';
import type { Agent, CliProviderStatus } from '@/types';
import { useMissionStore } from '@/missions/store';
import { isMissionEvent, type CommandInput } from '@/missions/types';
import { projectWorkspace, type EntitySelection } from '@/missions/projection';
import { EntityDetails } from '@/missions/EntityDetails';
import './agentWorkspace.css';

export function AgentWorkspacePage() {
  const projects = useProjectsStore();
  const store = useMissionStore();
  const connection = useConnectionStore(s => s.status.status);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [providers, setProviders] = useState<Record<string, CliProviderStatus>>({});
  const [catalogError, setCatalogError] = useState('');
  const [selection, setSelection] = useState<EntitySelection | null>(null);
  const [draft, setDraft] = useState('');
  const [instruction, setInstruction] = useState(false);
  const [filter, setFilter] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [selectedTask, setSelectedTask] = useState('');
  const [resolvingConflict, setResolvingConflict] = useState<string | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const setPage = useUiStore(s => s.setActivePage);
  const pid = projects.selectedProjectId;
  const snapshot = store.snapshot;
  const mission = snapshot?.mission;
  const instructionMode = instruction && !!mission && !['completed', 'cancelled', 'failed'].includes(mission.status);
  const active = mission && ['analyzing', 'running', 'reviewing', 'changes_requested', 'testing'].includes(mission.status);
  const { nodes, edges } = useMemo(() => projectWorkspace(snapshot, agents), [snapshot, agents]);

  const loadProjects = projects.loadProjects;
  useEffect(() => { void loadProjects(); }, [loadProjects]);
  useEffect(() => {
    if (!pid) return;
    void useMissionStore.getState().load(pid);
    let mounted = true;
    void Promise.all([agentsApi.list(), providerCliApi.listStatuses()]).then(([a, p]) => {
      if (mounted) { setAgents(a); setProviders(p); setCatalogError(''); }
    }).catch((e: unknown) => { if (mounted) setCatalogError(String(e)); });
    void settingsApi.get(`mission_draft:${pid}`).then(value => {
      if (mounted) setDraft(typeof value.value === 'string' ? value.value : '');
    }).catch((e: unknown) => { if (mounted) setCatalogError(String(e)); });
    return () => { mounted = false; };
  }, [pid, connection]);
  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void onBridgeEvent(event => {
      if (event.event === 'mission.changed' && isMissionEvent(event.payload)) {
        void useMissionStore.getState().event(event.payload);
      }
    }).then(fn => { if (disposed) fn(); else unlisten = fn; }).catch((e: unknown) => setCatalogError(String(e)));
    return () => { disposed = true; unlisten?.(); };
  }, []);

  async function send() {
    if (!draft.trim() || store.sending || !pid) return;
    if (instructionMode && mission) await store.command({ action: 'instruction', content: draft });
    else await store.submit(draft);
    if (!useMissionStore.getState().error) {
      setDraft('');
      await settingsApi.update(`mission_draft:${pid}`, '');
    }
    composer.current?.focus();
  }
  function act(input: CommandInput) { void store.command(input); }
  async function persistDraft() {
    if (pid) {
      try { await settingsApi.update(`mission_draft:${pid}`, draft); }
      catch (e) { setCatalogError(String(e)); }
    }
  }
  const selectedSession = snapshot?.sessions.find(s => selection?.kind === 'session' && s.id === selection.id);
  const sessionName = (id: string | null) => {
    const session = snapshot?.sessions.find(s => s.id === id);
    return agents.find(a => a.id === session?.agent_id)?.name ?? 'Equipe';
  };
  return (
    <div className="agent-workspace">
      <header className="workspace-toolbar">
        <div><h1>Agent Workspace</h1><span>Pedidos, colaboração e evidências</span></div>
        <label>Projeto <select aria-label="Projeto do workspace" value={pid ?? ''} onChange={e => projects.selectProject(e.target.value)}>
          <option value="" disabled>Selecione um projeto</option>
          {projects.projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
        <span role="status">Bridge: {connection}</span>
        <Button size="sm" variant="outline" onClick={() => useUiStore.getState().openDelivery()}>Delivery Center</Button>
        <Button size="sm" variant="outline" onClick={() => setPage('office')}>Pixel Office</Button>
        <Button size="sm" variant="outline" onClick={() => setPage('providers')}>Conexões</Button>
      </header>
      {(store.error || catalogError || projects.error) && <div className="workspace-error" role="alert">
        {store.error || catalogError || projects.error}
        <Button size="sm" onClick={() => { if (pid) void store.load(pid); void projects.loadProjects(); }}>Tentar novamente</Button>
      </div>}
      {!pid ? <div className="workspace-empty">Abra um projeto para começar. <Button onClick={() => setPage('projects')}>Abrir projetos</Button></div> : <>
        <div className="workspace-body">
          <aside className="workspace-queue" aria-label="Pedidos e tarefas">
            <h2>Pedidos</h2>
            {store.loading && <p role="status">Carregando missão…</p>}
            {!store.missions.length && <p>Envie o primeiro pedido. O líder propõe o trabalho e a equipe.</p>}
            {store.missions.map(m => <button className={`queue-item ${m.id === store.selectedId ? 'selected' : ''}`} key={m.id} onClick={() => void store.select(m.id)}>
              <strong>{m.request.slice(0, 90)}</strong><span>{m.status}</span>
            </button>)}
            <h2>Tarefas</h2>
            {snapshot?.tasks.map(t => <button className="queue-item" key={t.id} onClick={() => setSelection({ kind: 'task', id: t.id })}>{t.title}<span>{t.status}</span></button>)}
            {snapshot?.instructions.map(i => <div className="queue-item" key={i.id}><strong>{i.content}</strong><span>{i.disposition}</span><small>{i.reason}</small></div>)}
            <h2>Agentes permanentes</h2>
            {agents.filter(a => a.active && (!a.project_id || a.project_id === pid)).map(a => <button className="queue-item" key={a.id} onClick={() => setSelection({ kind: 'agent', id: a.id })}>
              {a.name}<small>{a.role || a.capabilities.map(c => c.name).join(' · ')} · {a.runtime_binding?.label ?? a.runtime_binding_id ?? a.provider}</small><span>{providers[a.provider]?.state ?? 'API / consulte Conexões'}</span><small>slots {a.slots_available ?? '—'}</small>
            </button>)}
          </aside>
          <main className="workspace-center">
            <div className="mission-control" aria-live="polite">
              <strong>{mission ? mission.status : 'Sua equipe está pronta para receber um pedido'}</strong>
              {mission?.reason && <p>{mission.reason}</p>}
              {mission && <div className="workspace-actions">
                <Button size="sm" disabled={!!active || store.sending} onClick={() => act({ action: 'analyze' })}>Analisar / replanejar</Button>
                <Button size="sm" disabled={!mission.current_plan_id || mission.status === 'awaiting_approval' || mission.status === 'awaiting_human_approval' || !!active || store.sending || ['completed', 'cancelled', 'failed'].includes(mission.status)} onClick={() => act({ action: mission.status === 'blocked' ? 'resume' : 'start' })}>{mission.status === 'blocked' ? 'Retomar' : 'Iniciar missão'}</Button>
                <Button size="sm" variant="outline" disabled={!active || store.sending} onClick={() => act({ action: 'pause' })}>Pausar</Button>
                <Button size="sm" variant="outline" disabled={store.sending || ['completed', 'cancelled', 'failed'].includes(mission.status)} onClick={() => act({ action: 'cancel' })}>Cancelar</Button>
              </div>}
            </div>
            <div className="collaboration-canvas" aria-label="Canvas de colaboração">
              <ReactFlow key={mission?.id ?? "agents"} nodes={nodes} edges={edges} nodesDraggable={false} nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null} fitView
                onNodeClick={(_, node) => setSelection({ kind: node.data.kind, id: node.data.entityId })}>
                <Background color="#314052" gap={24} /><Controls showInteractive={false} /><MiniMap pannable zoomable nodeColor="#537b91" />
              </ReactFlow>
            </div>
            {snapshot?.plans.length ? <details className="workspace-plan" open={mission?.status === 'planned'}>
              <summary>Plano v{snapshot.plans.at(-1)?.version} e motivos da escolha</summary>
              <p>{snapshot.plans.at(-1)?.summary}</p>
              {snapshot.plans.at(-1)?.choices.map(c => <p key={c.role}><strong>{c.role}: {agents.find(a => a.id === c.agent_id)?.name}</strong> — {c.reason}</p>)}
              {snapshot.plans.at(-1)?.tasks.map(t => <p key={t.key}>{t.title}: {t.acceptance.join('; ')}</p>)}
            </details> : null}
            {mission?.result && <article className="mission-result"><h2>Resultado consolidado</h2><pre>{mission.result}</pre></article>}
            {snapshot && (snapshot.worktrees?.length || snapshot.forecasts?.length || snapshot.integrations?.length || snapshot.quality_gates?.length || snapshot.conflicts?.length) ? <details className="workspace-plan" open>
              <summary>Execução paralela e integração</summary>
              {snapshot.worktrees?.map(w => <p key={w.id}><strong>{w.branch_name}</strong> · {w.status} · base {w.base_sha.slice(0, 8)}{w.head_sha ? ` → ${w.head_sha.slice(0, 8)}` : ''}</p>)}
              {snapshot.forecasts?.map(f => <p key={f.id}>Conflito {f.level}: {f.reason}{f.paths.length ? ` (${f.paths.join(', ')})` : ''}</p>)}
              {snapshot.integrations?.map(i => <p key={i.id}>Integração {i.result}: {i.source_branch} → {i.integration_branch}{i.commit_sha ? ` (${i.commit_sha.slice(0, 8)})` : ''}</p>)}
              {snapshot.quality_gates?.map(g => <p key={g.id}>Quality gate {g.name}: {g.passed ? 'aprovado' : `falhou (exit ${g.exit_code})`}</p>)}
              {snapshot.conflicts?.map(c => <p key={c.id} className="text-amber-600">Conflito {c.classification}: {c.status} · {c.files?.map(f => f.path).join(', ') || 'aguarda análise assistida'}</p>)}
              {snapshot.conflicts?.filter(c => c.status === 'detected' || c.status === 'awaiting_analysis' || c.status === 'changes_requested').map(c => <Button key={`assist-${c.id}`} size="sm" variant="outline" disabled={resolvingConflict === c.id} onClick={() => { const integrator = agents.find(a => a.name.endsWith('Vega'))?.id; const reviewer = agents.find(a => a.name.endsWith('Sentinel'))?.id; if (!integrator || !reviewer || !mission) return; setResolvingConflict(c.id); void invokeBridge('integration.conflict.assist', { mission_id: mission.id, conflict_id: c.id, integrator_agent_id: integrator, reviewer_agent_id: reviewer }).finally(() => setResolvingConflict(null)); }}>Iniciar resolução assistida</Button>)}
            </details> : null}
          </main>
          <aside className="workspace-details" aria-label="Detalhes e conversa">
            <h2>{selection?.kind ?? 'Missão'} · detalhes</h2>
            <EntityDetails selection={selection} snapshot={snapshot} agents={agents} />
            {selectedSession && <>
              <div className="workspace-actions"><Button size="sm" onClick={() => act({ action: 'pause', session_id: selectedSession.id })}>Pausar sessão</Button><Button size="sm" variant="outline" onClick={() => act({ action: 'cancel', session_id: selectedSession.id })}>Cancelar sessão</Button></div>
              <small>A colaboração pausa junto para manter as dependências consistentes.</small>
              <details open><summary>Terminal / logs da sessão</summary>{snapshot?.artifacts.filter(a => a.session_id === selectedSession.id && a.kind === 'log').map(a => <pre key={a.id}>{a.content}</pre>)}</details>
            </>}
            <h2>Conversa entre agentes</h2>
            <input aria-label="Filtrar conversa" placeholder="Nome, tipo ou conteúdo" value={filter} onChange={e => setFilter(e.target.value)} />
            <div className="agent-conversation" role="log" aria-label="Mensagens persistidas">
              {snapshot?.messages.filter(m => `${sessionName(m.from_session_id)} ${m.message_type} ${m.content}`.toLowerCase().includes(filter.toLowerCase())).map(m => <button className="message-item" key={m.id} onClick={() => setSelection({ kind: 'message', id: m.id })}>
                <strong>{sessionName(m.from_session_id)} → {sessionName(m.to_session_id)}</strong><span>{m.message_type} · {m.delivery_status}</span><p>{m.content}</p>
              </button>)}
            </div>
            <h2>Artefatos e alterações reais</h2>
            {snapshot?.artifacts.filter(a => a.kind !== 'log').map(a => <button className="queue-item" key={a.id} onClick={() => setSelection({ kind: 'artifact', id: a.id })}>{a.title}<small>{a.paths.join(', ')} {a.exit_code !== null ? `exit ${a.exit_code}` : ''}</small></button>)}
            {mission && <details><summary>Intervir na equipe</summary>
              <label>Agente<select aria-label="Agente para atribuição" value={selectedAgent} onChange={e => setSelectedAgent(e.target.value)}><option value="">Selecione</option>{agents.filter(a => a.active).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
              <label>Tarefa<select aria-label="Tarefa para reatribuição" value={selectedTask} onChange={e => setSelectedTask(e.target.value)}><option value="">Selecione</option>{snapshot?.tasks.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
              <Button size="sm" disabled={!!active || !selectedAgent || store.sending} onClick={() => act({ action: 'include_agent', agent_id: selectedAgent })}>Incluir agente</Button>
              <Button size="sm" disabled={!!active || !selectedAgent || !selectedTask || store.sending} onClick={() => act({ action: 'reassign', agent_id: selectedAgent, task_id: selectedTask })}>Reatribuir tarefa</Button>
              <Button size="sm" disabled={!['blocked', 'awaiting_approval', 'awaiting_human_approval'].includes(mission.status) || !draft.trim() || store.sending} onClick={() => act({ action: 'approve', content: draft })}>{mission.status === 'awaiting_human_approval' ? 'Aprovar entrega' : 'Registrar decisão e retomar'}</Button>
              <small>Pause antes de alterar atribuições. Decisões usam o texto do campo abaixo.</small>
            </details>}
          </aside>
        </div>
        <form className="mission-composer" onSubmit={e => { e.preventDefault(); void send().catch(e => setCatalogError(String(e))); }}>
          <label><input type="checkbox" checked={instructionMode} disabled={!mission || ['completed', 'cancelled', 'failed'].includes(mission.status)} onChange={e => setInstruction(e.target.checked)} /> Instrução para a missão selecionada</label>
          <div><textarea ref={composer} aria-label="Pedido ou instrução" placeholder="O que a equipe deve fazer neste projeto?" value={draft} onChange={e => setDraft(e.target.value)} onBlur={() => void persistDraft()} onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); void send().catch(e => setCatalogError(String(e))); } }} maxLength={8000} rows={2} />
            <Button type="submit" disabled={!draft.trim() || store.sending}>{store.sending ? 'Enviando…' : instructionMode ? 'Enviar instrução' : 'Enviar pedido'}</Button></div>
          <small>Ctrl/⌘ + Enter para enviar. O líder analisa instruções novas entre turnos. Rascunho salvo ao sair do campo.</small>
        </form>
      </>}
    </div>
  );
}
