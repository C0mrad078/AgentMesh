import type { PostMergeVerification, RollbackPlan } from '@/types/delivery';
import { Panel, Evidence, ExternalLink } from './Panel';
export function RollbackCard({ postMerge, plan, busy, onPropose }: { postMerge: PostMergeVerification | null; plan: RollbackPlan | null; busy: boolean; onPropose: (reason: string) => void }) {
  return <Panel title="Pós-merge e rollback por revert">
    {postMerge ? <><p>Verificação: {postMerge.status} · {postMerge.verified_at}</p><p>Target SHA observado: {postMerge.target_sha_observed}</p><Evidence value={postMerge.checks_run} /></> : <p>Sem verificação pós-merge registrada.</p>}
    {plan && <><p>Revert: {plan.strategy} · {plan.status}</p><p>Merge SHA: {plan.merge_commit_sha}</p><p>Branch: {plan.revert_branch}</p><ExternalLink url={plan.revert_pr_url}>Abrir PR de revert</ExternalLink></>}
    <form onSubmit={e => { e.preventDefault(); onPropose(String(new FormData(e.currentTarget).get('reason'))); }}><label>Motivo do rollback<textarea name="reason" required /></label><button disabled={busy} type="submit">Propor rollback por revert</button></form>
    <p>A proposta exige aprovação humana antes da execução.</p>
  </Panel>;
}
