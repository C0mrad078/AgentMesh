import type { DeliveryCandidateDetail } from '@/types/delivery';
import { Panel, Evidence } from './Panel';
import { safeText } from './presentation';
export function CandidateOverview({ detail: d }: { detail: DeliveryCandidateDetail }) {
  const s = d.snapshot;
  return <Panel title="Candidate e evidências congeladas">
    <p><strong>{d.candidate.id} · versão {d.candidate.version}</strong> · {d.candidate.status}</p>
    <dl className="delivery-facts"><dt>Missão / projeto</dt><dd>{s.mission_id} / {s.project_id}</dd><dt>Base SHA</dt><dd>{s.base_sha}</dd><dt>Integration SHA</dt><dd>{s.integration_sha}</dd><dt>Remote SHA</dt><dd>{d.remote_sha ?? 'unknown'}</dd><dt>Hash do diff</dt><dd>{s.diff_hash}</dd><dt>Snapshot</dt><dd>{s.id} · schema {s.schema_version} · {s.created_at}</dd></dl>
    <p>{s.diff_stat.files_changed} arquivos · +{s.diff_stat.insertions} / −{s.diff_stat.deletions}</p>
    <details><summary>Arquivos do diff ({d.diff_files.length})</summary>{d.diff_files.length ? d.diff_files.map(f => <p key={f.path}>{safeText(f.path)} · {f.status} · +{f.additions} / −{f.deletions}</p>) : <p>Nenhum arquivo informado.</p>}</details>
    <details><summary>Commits ({s.commits.length})</summary>{s.commits.map(c => <p key={c.sha}><code>{c.sha}</code> · {safeText(c.message)} · {safeText(c.author)} · {c.timestamp}</p>)}</details>
    <details open><summary>Tasks e agents ({s.tasks_summary.length})</summary>{s.tasks_summary.map(t => <p key={t.key}>{safeText(t.title)} · {t.status} · agente {safeText(t.agent_id)}</p>)}</details>
    <details><summary>Reviews e conflitos resolvidos</summary><Evidence value={s.reviews_summary} /><Evidence value={s.resolved_conflicts_summary} /></details>
    <details open><summary>Quality gates</summary><Evidence value={s.quality_gates_summary} /></details>
    <details open><summary>Riscos conhecidos</summary>{s.known_risks.length ? s.known_risks.map((r, i) => <p key={i}>{safeText(r)}</p>) : <p>Nenhum risco informado.</p>}</details>
  </Panel>;
}
