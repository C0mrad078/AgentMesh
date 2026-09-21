import type { PreflightReport } from '@/types/delivery';
import { Panel, Evidence } from './Panel';
import { safeText } from './presentation';
export function PreflightCard({ report, busy, onRun }: { report: PreflightReport | null; busy: boolean; onRun: () => void }) {
  return <Panel title="Preflight e segurança">
    <button disabled={busy} onClick={onRun}>{report ? 'Repetir preflight' : 'Executar preflight'}</button>
    {!report ? <p>Preflight ainda não executado.</p> : <>
      <p role="status">{report.status} · risco {report.risk_level} · versão {report.version}</p>
      <ul>{([['Remote acessível', report.remote_reachable], ['Base atualizada', report.base_up_to_date], ['Integration limpa', report.clean_integration_tree], ['Quality gates', report.quality_gate_passed], ['Busca de segredos', report.secret_scan_passed]] as const).map(([label, passed]) => <li key={label}>{label}: {passed ? 'aprovado' : 'falhou'}</li>)}</ul>
      {report.blocking_reasons.map((r, i) => <p role="alert" key={i}>{safeText(r)}</p>)}
      <h3>Segredos encontrados</h3>{report.secret_findings.length ? report.secret_findings.map((f, i) => <p key={i}>{safeText(f.file_path)}:{f.line_number} · {safeText(f.rule_id)} · <code>[conteúdo mascarado]</code></p>) : <p>Nenhum achado informado.</p>}
      <h3>Arquivos grandes / binários</h3><Evidence value={report.large_binary_findings} />
      <h3>Migrations e lockfiles</h3><Evidence value={report.migration_lockfile_check} />
    </>}
  </Panel>;
}
