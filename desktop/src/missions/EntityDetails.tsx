import type { Agent } from '@/types';
import type { EntitySelection } from './projection';
import type { MissionSnapshot } from './types';
export function EntityDetails({ selection, snapshot, agents }: {
  selection: EntitySelection | null; snapshot: MissionSnapshot | null; agents: Agent[];
}) {
  if (selection?.kind === 'agent') {
    const a = agents.find(a => a.id === selection.id);
    return a ? <article><h3>{a.name}</h3><p>{a.description}</p><p>{a.role} · {a.provider} · {a.model || 'Padrão'}</p><p>Especialidades: {a.capabilities.map(c => c.name).join(', ')}</p><p>Permissões: {a.permissions.can_write_files ? 'leitura e escrita' : 'somente leitura'}{a.permissions.can_run_terminal ? ', terminal' : ''}</p><details><summary>Instruções do agente</summary><pre>{a.system_prompt || 'Sem instruções adicionais.'}</pre></details></article> : null;
  }
  if (!snapshot) return <p>Selecione um agente ou envie um pedido.</p>;
  if (selection?.kind === 'session') {
    const s = snapshot.sessions.find(s => s.id === selection.id);
    const assignment = snapshot.assignments.find(a => a.session_id === s?.id);
    return s ? <article><h3>{agents.find(a => a.id === s.agent_id)?.name}</h3><p>Sessão: {s.status}</p><p>Papel: {assignment?.role}</p><p>{assignment?.reason}</p><p>Início: {s.started_at ? new Date(s.started_at).toLocaleString() : 'Ainda não iniciada'}</p><details><summary>Identificação da sessão</summary><p>{s.id}</p><p>CLI: {s.external_session_id ?? 'Ainda não iniciado'}</p></details></article> : null;
  }
  if (selection?.kind === 'task') {
    const t = snapshot.tasks.find(t => t.id === selection.id);
    return t ? <article><h3>{t.title}</h3><p>{t.status}</p><p>{t.description}</p>{snapshot.reviews.filter(r => r.task_id === t.id).map(r => <p key={r.id}>Revisão {r.round}: {r.verdict} — {r.justification}</p>)}</article> : null;
  }
  if (selection?.kind === 'message') {
    const m = snapshot.messages.find(m => m.id === selection.id);
    return m ? <article><h3>{m.message_type}</h3><p>{m.content}</p><p>{m.delivery_status} · {new Date(m.timestamp).toLocaleString()}</p>{m.reply_to && <p>Em resposta a: {snapshot.messages.find(previous => previous.id === m.reply_to)?.content}</p>}{m.artifact_ids.map(id => <details key={id}><summary>{snapshot.artifacts.find(a => a.id === id)?.title}</summary><pre>{snapshot.artifacts.find(a => a.id === id)?.content}</pre></details>)}</article> : null;
  }
  if (selection?.kind === 'artifact') {
    const a = snapshot.artifacts.find(a => a.id === selection.id);
    return a ? <article><h3>{a.title}</h3><p>{a.paths.join(', ')}</p>{a.command.length > 0 && <p>{a.command.join(' ')} · exit {a.exit_code}</p>}<pre>{a.content}</pre></article> : null;
  }
  return <article><h3>{snapshot.mission.request}</h3><p>{snapshot.mission.status}</p><p>{snapshot.mission.reason}</p><p>{snapshot.events.length} eventos persistidos.</p></article>;
}
