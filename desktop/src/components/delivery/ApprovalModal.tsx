import { useState } from 'react';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import type { DeliveryAction, DeliveryCandidateDetail } from '@/types/delivery';
import { actionLabels } from './presentation';
export function ApprovalModal({ action, detail, busy, onClose, onSubmit }: { action: DeliveryAction | null; detail: DeliveryCandidateDetail; busy: boolean; onClose: () => void; onSubmit: (decision: 'approved' | 'rejected', actor: string, reason: string) => Promise<void> }) {
  const [actor, setActor] = useState('');
  const [reason, setReason] = useState('');
  return <Dialog open={!!action} onOpenChange={open => { if (!open && !busy) onClose(); }}><DialogContent className="delivery-dialog">
    <DialogTitle>Decisão humana: {action ? actionLabels[action] : ''}</DialogTitle>
    <DialogDescription>Revise a versão, o destino e o SHA antes de registrar sua decisão. A execução remota é uma ação separada.</DialogDescription>
    <p>Candidate {detail.candidate.id} · versão {detail.candidate.version}</p><p>{detail.remote_binding?.remote_name} → {detail.remote_binding?.target_branch}</p><p className="break-all">SHA {detail.pull_request?.head_sha ?? detail.snapshot.integration_sha}</p>
    <form onSubmit={e => { e.preventDefault(); void onSubmit('approved', actor.trim(), reason.trim()); }}>
      <label>Identificação do aprovador<input required value={actor} onChange={e => setActor(e.target.value)} /></label>
      <label>Motivo da decisão<textarea value={reason} onChange={e => setReason(e.target.value)} /></label>
      <div className="delivery-actions"><button disabled={busy || !actor.trim()} type="submit">Registrar aprovação</button><button disabled={busy || !actor.trim()} type="button" onClick={() => void onSubmit('rejected', actor.trim(), reason.trim())}>Rejeitar</button><button disabled={busy} type="button" onClick={onClose}>Cancelar</button></div>
    </form>
  </DialogContent></Dialog>;
}
