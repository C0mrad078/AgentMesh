import type { CIWorkflowRun } from '@/types/delivery';
import { Panel, Evidence, ExternalLink } from './Panel';
import { safeText } from './presentation';
export function CiStatusCard({ runs, busy, onRefresh }: { runs: CIWorkflowRun[]; busy: boolean; onRefresh: () => void }) {
  return <Panel title="CI e status checks"><button disabled={busy} onClick={onRefresh}>Consultar CI</button>
    {!runs.length && <p>Nenhum check observado.</p>}{runs.map(r => <article key={r.id}><h3>{safeText(r.name)}</h3><p>{r.status} · {r.conclusion}</p><p>Commit {r.commit_sha}</p><ExternalLink url={r.run_url}>Abrir execução</ExternalLink><details><summary>Logs sanitizados</summary><Evidence value={r.logs_sanitized} /></details></article>)}
  </Panel>;
}
