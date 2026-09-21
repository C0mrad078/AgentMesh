import { useState } from 'react';
import type { RemoteRepositoryBinding, RemoteRepositoryBindingInput } from '@/types/delivery';
import { Panel, Evidence } from './Panel';
export function RemoteBindingCard({ binding, projectId, busy, onSave, onLoad }: { binding: RemoteRepositoryBinding | null; projectId: string; busy: boolean; onSave: (input: RemoteRepositoryBindingInput) => void; onLoad?: () => void }) {
  const [editing, setEditing] = useState(false);
  return <Panel title="Remote e target branch">
    {binding ? <><p>{binding.provider} · {binding.remote_name} → {binding.target_branch}</p><Evidence value={binding.remote_url_sanitized} /><p>Autenticação: {binding.auth_detected ? binding.auth_type : 'não detectada'} · verificado {binding.last_verified_at ?? 'unknown'}</p><Evidence value={{ permissions: binding.permissions, protections: binding.branch_protections }} /></> : <p>Binding não disponível nesta visualização. Consulte ou configure o remote.</p>}
    <button disabled={busy || !projectId || !onLoad} onClick={onLoad}>Consultar binding</button>
    <button onClick={() => setEditing(!editing)} aria-expanded={editing}>Configurar remote</button>
    {editing && <form onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); onSave({ project_id: projectId, provider: f.get('provider') as 'git' | 'github', remote_name: String(f.get('remote')), remote_url: String(f.get('url')), target_branch: String(f.get('target')), default_merge_method: f.get('method') as RemoteRepositoryBindingInput['default_merge_method'] }); }}>
      <label>Provider<select name="provider" defaultValue={binding?.provider ?? 'github'}><option value="github">GitHub</option><option value="git">Git genérico</option></select></label>
      <label>Remote name<input name="remote" required defaultValue={binding?.remote_name ?? 'origin'} /></label>
      <label>URL do repositório (sem credenciais)<input name="url" required defaultValue={binding?.remote_url_sanitized ?? ''} autoComplete="off" /></label>
      <label>Target branch<input name="target" required defaultValue={binding?.target_branch ?? 'main'} /></label>
      <label>Método de merge<select name="method" defaultValue={binding?.default_merge_method ?? 'squash'}><option>squash</option><option>merge</option><option>rebase</option></select></label>
      <button disabled={busy || !projectId} type="submit">Salvar binding</button>
    </form>}
  </Panel>;
}
