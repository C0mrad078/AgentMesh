import { useEffect, useState } from 'react';
import { useDeliveryStore, operationKey } from '@/stores/deliveryStore';
import { deliveryApi } from '@/services/deliveryApi';
import { useUiStore } from '@/stores/uiStore';
import { useProjectsStore } from '@/stores/projectsStore';
import { useMissionStore } from '@/missions/store';
import type { DeliveryAction, RemoteRepositoryBinding } from '@/types/delivery';
import { CandidateOverview } from '@/components/delivery/CandidateOverview';
import { PreflightCard } from '@/components/delivery/PreflightCard';
import { RemoteBindingCard } from '@/components/delivery/RemoteBindingCard';
import { PullRequestCard } from '@/components/delivery/PullRequestCard';
import { CiStatusCard } from '@/components/delivery/CiStatusCard';
import { FailureFixCard } from '@/components/delivery/FailureFixCard';
import { ApprovalModal } from '@/components/delivery/ApprovalModal';
import { RollbackCard } from '@/components/delivery/RollbackCard';
import { TelemetryCard } from '@/components/delivery/TelemetryCard';
import { Panel, Evidence } from '@/components/delivery/Panel';
import { actionLabels, safeText } from '@/components/delivery/presentation';
import './deliveryCenter.css';
export function DeliveryCenterPage() {
  const store = useDeliveryStore();
  const candidateId = useUiStore(s => s.deliveryCandidateId);
  const openDelivery = useUiStore(s => s.openDelivery);
  const [projectId, setProjectId] = useState(useProjectsStore.getState().selectedProjectId ?? '');
  const [missionId, setMissionId] = useState(useMissionStore.getState().selectedId ?? '');
  const [approval, setApproval] = useState<DeliveryAction | null>(null);
  const [copyMessage, setCopyMessage] = useState('');
  const [loadedBinding, setLoadedBinding] = useState<RemoteRepositoryBinding | null>(null);
  useEffect(() => { void useDeliveryStore.getState().load(); return useDeliveryStore.getState().subscribe(); }, []);
  useEffect(() => { void useDeliveryStore.getState().select(candidateId); }, [candidateId]);
  const d = store.detail;
  const run = (op: () => Promise<unknown>) => { void store.run(op); };
  async function createCandidate() {
    await store.run(async () => { const created = await deliveryApi.create(missionId.trim(), projectId.trim()); openDelivery(created.candidate.id); });
  }
  function execute(action: DeliveryAction) {
    if (!d) return;
    const id = d.candidate.id;
    const key = operationKey(d, action);
    const commands = { push: () => deliveryApi.push(id, key), pr_create: () => deliveryApi.createPr(id, key), pr_update: () => deliveryApi.updatePr(id, key), merge: () => deliveryApi.merge(id, key), rollback: () => deliveryApi.rollback(id, key) };
    run(commands[action]);
  }
  async function copyReport() {
    if (!d) return;
    // Only the sanitized projection is copied; secret samples are always suppressed.
    const report = { ...d, preflight: d.preflight ? { ...d.preflight, secret_findings: d.preflight.secret_findings.map(f => ({ ...f, masked_sample: '[conteúdo mascarado]' })) } : null };
    try { await navigator.clipboard.writeText(safeText(JSON.stringify(report, null, 2))); setCopyMessage('Relatório sanitizado copiado.'); }
    catch { setCopyMessage('Não foi possível copiar o relatório.'); }
  }
  return <div className="delivery-center">
    <header className="delivery-header"><div><h1>Delivery Center</h1><p>Evidências, aprovações e entrega controlada</p></div><div className="delivery-actions"><button onClick={() => useUiStore.getState().setActivePage('collaboration')}>Agent Workspace</button><button disabled={store.busy} onClick={() => void store.refresh()}>Atualizar estado</button></div></header>
    {store.error && <div role="alert" className="delivery-alert">{store.error}<button disabled={store.busy} onClick={() => void store.refresh()}>Tentar novamente</button></div>}
    {(store.loading || store.listLoading || store.busy || store.progress) && <p role="status" aria-live="polite">{store.loading || store.listLoading ? 'Carregando delivery…' : store.busy ? 'Operação em andamento…' : store.progress}</p>}
    <div className="delivery-layout"><aside aria-label="Candidates" className="delivery-panel"><h2>Candidates</h2>
      {!store.listLoading && !store.candidates.length && <p>Nenhum candidate criado.</p>}
      {store.candidates.map(c => <button className="delivery-candidate" aria-current={c.id === candidateId ? 'page' : undefined} key={c.id} onClick={() => openDelivery(c.id)}><strong>{safeText(c.mission_id)} · v{c.version}</strong><span>{c.status} · risco {c.risk_level}</span>{c.has_pending_approvals && <span>Aprovação pendente</span>}</button>)}
      <form onSubmit={e => { e.preventDefault(); void createCandidate(); }}><h3>Criar candidate</h3><label>Project ID<input required value={projectId} onChange={e => setProjectId(e.target.value)} /></label><label>Mission ID<input required value={missionId} onChange={e => setMissionId(e.target.value)} /></label><button disabled={store.busy || !projectId.trim() || !missionId.trim()} type="submit">Congelar candidate</button></form>
      {!d && <RemoteBindingCard key={projectId} projectId={projectId} binding={loadedBinding?.project_id === projectId ? loadedBinding : null} busy={store.busy} onLoad={() => run(async () => setLoadedBinding(await deliveryApi.binding(projectId)))} onSave={input => run(async () => setLoadedBinding(await deliveryApi.saveBinding(input)))} />}
    </aside><div className="delivery-content" aria-busy={store.loading || store.busy}>
      {!d && !store.loading && <Panel title="Selecione uma entrega"><p>Abra um candidate ou crie um a partir de uma integração aprovada.</p></Panel>}
      {d && <>
        {(d.recovery.is_blocked || d.recovery.recovery_reason) && <Panel title="Bloqueio e recuperação"><p role="alert">{safeText(d.recovery.recovery_reason ?? 'Entrega bloqueada pelo backend.')}</p><p>Ação sugerida: {d.recovery.suggested_action ?? 'unknown'}</p><button disabled={store.busy} onClick={() => void store.refresh()}>Recuperar estado persistido</button></Panel>}
        <CandidateOverview detail={d} />
        <div className="delivery-actions"><button onClick={() => void copyReport()}>Copiar relatório sanitizado</button><span role="status">{copyMessage}</span></div>
        <RemoteBindingCard key={d.remote_binding?.id ?? d.candidate.project_id} binding={d.remote_binding} projectId={d.candidate.project_id} busy={store.busy} onLoad={() => run(() => deliveryApi.binding(d.candidate.project_id))} onSave={input => run(() => deliveryApi.saveBinding(input))} />
        <PreflightCard report={d.preflight} busy={store.busy} onRun={() => run(() => deliveryApi.preflight(d.candidate.id))} />
        <Panel title="Aprovações humanas"><p>Candidate v{d.candidate.version}. O backend valida permissões, gates e SHA antes de executar.</p>
          {!d.pending_approvals.length && <p>Nenhuma aprovação pendente.</p>}
          <div className="delivery-actions">{d.pending_approvals.map(action => <button key={action} disabled={store.busy} onClick={() => setApproval(action)}>Revisar: {actionLabels[action]}</button>)}</div>
          <details><summary>Histórico de decisões</summary><Evidence value={d.approvals} /></details>
        </Panel>
        <Panel title="Executar operação aprovada"><p>Registrar uma aprovação não executa a operação automaticamente.</p><div className="delivery-actions">{(Object.keys(actionLabels) as DeliveryAction[]).map(a => <button key={a} disabled={store.busy} onClick={() => execute(a)}>{actionLabels[a]}</button>)}</div></Panel>
        <PullRequestCard pr={d.pull_request} operations={d.remote_operations} />
        <CiStatusCard runs={d.ci_runs} busy={store.busy} onRefresh={() => run(() => deliveryApi.ci(d.candidate.id))} />
        <FailureFixCard findings={d.ci_findings} busy={store.busy} onAssign={(finding, agent) => run(() => deliveryApi.assignFix(d.candidate.id, finding, agent))} />
        <RollbackCard postMerge={d.post_merge} plan={d.rollback_plan ?? d.rollback ?? null} busy={store.busy} onPropose={reason => run(() => deliveryApi.proposeRollback(d.candidate.id, reason))} />
        <TelemetryCard phases={d.telemetry} />
        <Panel title="Etapas e recovery"><Evidence value={d.internal_steps} /></Panel>
        <ApprovalModal key={`${d.candidate.id}:${d.candidate.version}:${d.pull_request?.head_sha ?? d.snapshot.integration_sha}:${approval}`} action={approval} detail={d} busy={store.busy} onClose={() => setApproval(null)} onSubmit={async (decision, actor, reason) => { if (approval && await store.run(() => deliveryApi.approve(d.candidate.id, approval, decision, actor, reason))) setApproval(null); }} />
      </>}
    </div></div>
  </div>;
}
