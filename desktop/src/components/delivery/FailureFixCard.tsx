import type { CIFailureFinding } from '@/types/delivery';
import { Panel } from './Panel';
import { safeText } from './presentation';
export function FailureFixCard({ findings, busy, onAssign }: { findings: CIFailureFinding[]; busy: boolean; onAssign: (id: string, agent?: string) => void }) {
  return <Panel title="Falhas de CI e correções">{!findings.length && <p>Nenhuma falha de CI registrada.</p>}{findings.map(f => <article key={f.id}><h3>{f.classification} · {f.status}</h3><p>Check {f.check_id} · ciclo {f.iteration}</p><p>Task: {f.assigned_task_id ?? 'não atribuída'} · agent: {f.assigned_agent_id ?? 'não atribuído'}</p><p>Worktree: {safeText(f.worktree_path)}</p>
    <form onSubmit={e => { e.preventDefault(); const agent = String(new FormData(e.currentTarget).get('agent') ?? '').trim(); onAssign(f.id, agent || undefined); }}><label>Agent ID para {f.id}<input name="agent" placeholder="Seleção automática pelo backend" /></label><button disabled={busy} type="submit">Atribuir correção</button></form>
  </article>)}<p>As correções revisadas e testadas geram uma nova versão, disponível na lista de candidates.</p></Panel>;
}
