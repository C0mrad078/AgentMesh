import type { PullRequestRecord, RemoteOperation } from '@/types/delivery';
import { Panel, Evidence, ExternalLink } from './Panel';
import { safeText } from './presentation';
export function PullRequestCard({ pr, operations }: { pr: PullRequestRecord | null; operations: RemoteOperation[] }) {
  return <Panel title="Branch de entrega e Pull Request">
    {pr ? <><p>{safeText(pr.title)} · #{pr.pr_number ?? 'unknown'} · {pr.state}</p><p>{pr.delivery_branch} → {pr.target_branch}</p><p>Head: {pr.head_sha}<br />Base: {pr.base_sha}</p><ExternalLink url={pr.pr_url}>Abrir PR</ExternalLink><details><summary>Descrição do PR</summary><Evidence value={pr.body} /></details></> : <p>PR ainda não criado. A branch e o PR exigem aprovações separadas.</p>}
    <h3>Operações remotas</h3>{operations.length ? operations.map(o => <details key={o.id}><summary>{o.operation_type} · {o.status} · tentativas {o.attempts}</summary><p>Aprovado por {safeText(o.approved_by)}</p><Evidence value={o.payload_sanitized} /><Evidence value={o.result} />{o.error_sanitized && <p role="alert">{safeText(o.error_sanitized)}</p>}</details>) : <p>Nenhuma operação registrada.</p>}
  </Panel>;
}
