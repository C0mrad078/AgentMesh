import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Download, HardDrive, RefreshCw, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useReliabilityStore } from '@/stores/reliabilityStore';
import type { BackupInfoDTO } from '@/types/reliability';

const APP_VERSION = '0.1.0-rc.1';
const prettyBytes = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(2)} MB`;
const prettyDate = (value: string) => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium', timeStyle: 'short' }).format(date); };
const exportName = (value: unknown): string | null => {
  if (typeof value === 'string') return value.split(/[\\/]/).filter(Boolean).at(-1) ?? null;
  if (typeof value !== 'object' || value === null) return null;
  for (const key of ['path', 'output_path', 'file_path', 'archive_path', 'name']) {
    const item = (value as Record<string, unknown>)[key];
    if (typeof item === 'string') return item.split(/[\\/]/).filter(Boolean).at(-1) ?? item;
  }
  return null;
};

function BackupCard({ backup, currentSchema, onRestore, disabled }: { backup: BackupInfoDTO; currentSchema: number | null; onRestore: (backup: BackupInfoDTO) => void; disabled: boolean }) {
  const { manifest } = backup;
  const shaValid = /^[a-f0-9]{64}$/i.test(manifest.sha256);
  const schemaCompatible = currentSchema === null ? null : manifest.schema_version <= currentSchema;
  return <article className="rounded-md border border-border p-3" data-testid="backup-row">
    <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h3 className="break-all text-sm font-semibold">{manifest.backup_id}</h3><p className="text-xs text-muted-foreground">{prettyDate(manifest.created_at)} · schema {manifest.schema_version} · {prettyBytes(manifest.db_size_bytes)}</p></div><Button size="sm" variant="outline" disabled={disabled || !shaValid || schemaCompatible === false} onClick={() => onRestore(backup)}>Restaurar…</Button></div>
    <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-[120px_1fr]"><dt className="font-medium">SHA-256</dt><dd className="break-all font-mono">{manifest.sha256}</dd><dt className="font-medium">Tabelas</dt><dd>{manifest.tables_count}</dd><dt className="font-medium">Protegido</dt><dd>{manifest.protected ? 'Sim' : 'Não'}</dd></dl>
    <p className="mt-2 text-xs" role="status">Metadados locais: {shaValid ? 'formato SHA-256 válido' : 'SHA-256 inválido'} · {schemaCompatible === null ? 'compatibilidade não verificável ainda' : schemaCompatible ? 'schema não é mais novo que o atual' : 'schema incompatível'}. O backend revalida checksum e integridade antes de trocar o banco.</p>
  </article>;
}

export function DiagnosticsCenterPage() {
  const store = useReliabilityStore();
  const refresh = useReliabilityStore(state => state.refresh);
  const [protectedBackup, setProtectedBackup] = useState(false);
  const [restoreCandidate, setRestoreCandidate] = useState<BackupInfoDTO | null>(null);
  const [humanConfirmed, setHumanConfirmed] = useState(false);
  useEffect(() => { void refresh(); }, [refresh]);
  const report = store.diagnostics;
  const currentSchema = useMemo(() => report?.metadata.applied_migrations.length ? Math.max(...report.metadata.applied_migrations) : null, [report]);
  const integrity = report?.database_health.pragmas.integrity_check;
  const integrityHealthy = integrity === 'ok';
  const exportFile = exportName(store.exportResult);

  async function confirmRestore() {
    if (!restoreCandidate || !humanConfirmed || store.operation) return;
    const completed = await store.restoreBackup(restoreCandidate.manifest.backup_id);
    if (completed) { setRestoreCandidate(null); setHumanConfirmed(false); }
  }

  return <main className="mx-auto flex w-full max-w-6xl flex-col gap-5 pb-8" aria-labelledby="diagnostics-title">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Production readiness</p><h1 id="diagnostics-title" className="text-2xl font-bold">Diagnostics Center</h1><p className="text-sm text-muted-foreground">Saúde local, evidências sanitizadas e recuperação do banco.</p></div>
      <div className="flex gap-2"><Button variant="outline" disabled={store.loading || !!store.operation} onClick={() => void store.refresh()}><RefreshCw aria-hidden="true" className="size-4" />Atualizar</Button><Button disabled={!!store.operation} onClick={() => void store.exportDiagnostics()}><Download aria-hidden="true" className="size-4" />Exportar diagnostics bundle (.zip)</Button></div>
    </header>

    {store.loading && <p role="status" aria-live="polite">Coletando informações locais…</p>}
    {store.progress && <p className="rounded-md border border-border px-3 py-2 text-sm" role="status" aria-live="polite">{store.progress}</p>}
    {store.errors.diagnostics && <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive p-3 text-sm" role="alert"><span>Falha ao coletar diagnósticos: {store.errors.diagnostics}</span><Button variant="outline" size="sm" onClick={() => void store.loadDiagnostics()}>Tentar novamente</Button></div>}
    {store.errors.operation && <p className="rounded-md border border-destructive p-3 text-sm" role="alert">{store.errors.operation}</p>}
    {store.exportResult !== null && <p className="rounded-md border border-border p-3 text-sm" role="status">Exportação confirmada pelo backend.{exportFile ? ` Arquivo: ${exportFile}` : ' O bridge confirmou a operação; caminho de saída não foi definido no contrato.'}</p>}

    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Estado global">
      <Card><CardHeader className="pb-2"><CardDescription>Versão</CardDescription><CardTitle className="text-lg">{report?.metadata.app_version ?? APP_VERSION}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">Release Candidate {APP_VERSION}</CardContent></Card>
      <Card><CardHeader className="pb-2"><CardDescription>Sistema</CardDescription><CardTitle className="text-base">{report ? `${report.metadata.os} · ${report.metadata.architecture}` : 'Aguardando diagnóstico'}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">{report ? `Python ${report.metadata.python_version} · Node ${report.metadata.node_version ?? 'não informado'}` : 'Sem relatório persistido'}</CardContent></Card>
      <Card><CardHeader className="pb-2"><CardDescription>SQLite integridade</CardDescription><CardTitle className="flex items-center gap-2 text-base">{integrityHealthy ? <CheckCircle2 aria-hidden="true" className="size-4 text-green-600" /> : integrity === undefined ? <AlertTriangle aria-hidden="true" className="size-4 text-amber-600" /> : <AlertTriangle aria-hidden="true" className="size-4 text-destructive" />}{integrity === undefined ? 'Não verificada' : String(integrity)}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">{report ? `${prettyBytes(report.database_health.file_size_bytes)} · ${report.database_health.tables_count} tabelas` : 'Aguardando diagnóstico'}</CardContent></Card>
      <Card><CardHeader className="pb-2"><CardDescription>Uptime observado</CardDescription><CardTitle className="text-base">{report ? `${Math.floor(report.metadata.uptime_seconds / 60)} min` : '—'}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">Memória {report?.metadata.memory_usage_bytes === null || report?.metadata.memory_usage_bytes === undefined ? 'não informada' : prettyBytes(report.metadata.memory_usage_bytes)}</CardContent></Card>
    </section>

    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck aria-hidden="true" className="size-4" />Providers e bindings</CardTitle><CardDescription>Somente disponibilidade e campos sanitizados retornados pelo backend.</CardDescription></CardHeader><CardContent className="space-y-4">
        <div><h2 className="mb-2 text-sm font-semibold">Providers / CLIs</h2>{!report?.providers.length ? <p className="text-sm text-muted-foreground">Nenhum status de provider disponível.</p> : <ul className="space-y-2">{report.providers.map(provider => <li key={provider.name} className="flex flex-wrap items-center justify-between gap-2 rounded border border-border p-2 text-sm"><span>{provider.name}{provider.version ? ` · ${provider.version}` : ''}</span><span className="text-xs text-muted-foreground">{provider.available === undefined ? 'status não informado' : provider.available ? 'disponível' : 'indisponível'}</span></li>)}</ul>}</div>
        <div><h2 className="mb-2 text-sm font-semibold">Runtime bindings</h2>{!report?.runtime_bindings.length ? <p className="text-sm text-muted-foreground">Nenhum binding reportado.</p> : <ul className="space-y-2">{report.runtime_bindings.map((binding, index) => <li key={`${binding.provider ?? 'binding'}-${index}`} className="rounded border border-border p-2 text-sm"><strong>{binding.provider ?? 'Provider não informado'}</strong><span className="ml-2 text-xs text-muted-foreground">{binding.health ?? 'estado não informado'}</span><p className="text-xs text-muted-foreground">Capacidade configurada {binding.configured_capacity ?? '—'} · observada {binding.observed_capacity ?? '—'} · reservada {binding.reserved_slots ?? '—'}</p></li>)}</ul>}</div>
      </CardContent></Card>

      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Database aria-hidden="true" className="size-4" />Migrations aplicadas</CardTitle><CardDescription>Versões lidas do schema_migrations; nenhuma sequência é inferida.</CardDescription></CardHeader><CardContent>{report?.metadata.applied_migrations.length ? <ol className="grid max-h-56 grid-cols-3 gap-2 overflow-auto sm:grid-cols-4" aria-label="Migrations aplicadas">{report.metadata.applied_migrations.map(version => <li key={version} className="rounded border border-border px-2 py-1 font-mono text-xs">{String(version).padStart(4, '0')}</li>)}</ol> : <p className="text-sm text-muted-foreground">Ainda não foi possível confirmar migrations aplicadas.</p>}<p className="mt-3 text-xs text-muted-foreground">{report ? `${report.metadata.applied_migrations.length} migration(s) reportada(s).` : 'Sem dados disponíveis.'}</p></CardContent></Card>
    </div>

    <Card><CardHeader><CardTitle className="flex items-center gap-2"><HardDrive aria-hidden="true" className="size-4" />Backup &amp; Restore</CardTitle><CardDescription>Snapshots consistentes, manifests imutáveis e restore com safety snapshot.</CardDescription></CardHeader><CardContent className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3"><label className="flex items-center gap-2 text-sm"><input id="protected-backup" type="checkbox" checked={protectedBackup} onChange={event => setProtectedBackup(event.target.checked)} /><span>Proteger este backup da retenção automática</span></label><Button disabled={!!store.operation} onClick={() => void store.createBackup(protectedBackup)}>{store.operation === 'backup-create' ? 'Criando…' : 'Criar backup consistente'}</Button></div>
      {store.errors.backups && <p role="alert" className="text-sm text-destructive">Falha ao listar backups: {store.errors.backups} <Button size="sm" variant="outline" onClick={() => void store.loadBackups()}>Tentar novamente</Button></p>}
      {!store.backups.length && !store.errors.backups ? <p className="rounded border border-dashed border-border p-4 text-sm text-muted-foreground">Nenhum backup disponível.</p> : <ul className="space-y-3">{store.backups.map(backup => <li key={backup.manifest.backup_id}><BackupCard backup={backup} currentSchema={currentSchema} disabled={!!store.operation} onRestore={candidate => { setRestoreCandidate(candidate); setHumanConfirmed(false); }} /></li>)}</ul>}
      {store.restoreResult && <div className="rounded border border-green-600/40 bg-green-600/5 p-3 text-sm" role="status"><p className="font-semibold">Restore verificado pelo backend: {store.restoreResult.backup_id}</p><p>Safety snapshot criado: <code className="break-all">{store.restoreResult.safety_snapshot_path}</code></p><p>Schema restaurado: {store.restoreResult.schema_version}</p></div>}
    </CardContent></Card>

    <Card><CardHeader><CardTitle>Logs sanitizados recentes</CardTitle><CardDescription>Últimas linhas aprovadas pelo redator de segredos; conteúdos não estruturados são omitidos no backend.</CardDescription></CardHeader><CardContent>{report?.logs_sanitized.length ? <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 font-mono text-xs" aria-label="Logs sanitizados">{report.logs_sanitized.join('\n')}</pre> : <p className="text-sm text-muted-foreground">Nenhum log sanitizado disponível.</p>}</CardContent></Card>

    <Dialog open={restoreCandidate !== null} onOpenChange={open => { if (!open && store.operation !== 'restore') { setRestoreCandidate(null); setHumanConfirmed(false); } }}>
      <DialogContent aria-describedby="restore-impact-description">
        <DialogHeader><DialogTitle>Confirmar restore de backup</DialogTitle><DialogDescription id="restore-impact-description">Esta operação substituirá o banco ativo caso as validações do backend passem.</DialogDescription></DialogHeader>
        {restoreCandidate && <div className="space-y-3 text-sm"><div className="rounded border border-border p-3"><p><strong>Backup:</strong> {restoreCandidate.manifest.backup_id}</p><p><strong>Snapshot criado:</strong> {prettyDate(restoreCandidate.manifest.created_at)}</p><p><strong>Schema:</strong> {restoreCandidate.manifest.schema_version} (atual observado: {currentSchema ?? 'não informado'})</p><p><strong>Tamanho:</strong> {prettyBytes(restoreCandidate.manifest.db_size_bytes)}</p><p><strong>SHA-256:</strong> <code className="break-all">{restoreCandidate.manifest.sha256}</code></p></div><ul className="list-inside list-disc text-xs text-muted-foreground"><li>O backend revalida SHA-256, tamanho, SQLite integrity_check, foreign keys e compatibilidade antes da troca.</li><li>O backend deve criar safety snapshot e realizar a troca atômica; em falha, a resposta do backend determinará a recuperação.</li><li>A tela não inicia confirmação otimista: só exibirá restore concluído após resposta confirmada.</li></ul><label className="flex items-start gap-2 rounded border border-amber-500/40 p-3"><input id="restore-confirm" type="checkbox" checked={humanConfirmed} onChange={event => setHumanConfirmed(event.target.checked)} /><span>Entendo que o conteúdo atual do banco será substituído por este backup se a validação for aprovada.</span></label></div>}
        <DialogFooter><Button variant="outline" disabled={store.operation === 'restore'} onClick={() => setRestoreCandidate(null)}>Cancelar</Button><Button variant="destructive" disabled={!restoreCandidate || !humanConfirmed || !!store.operation} onClick={() => void confirmRestore()}>{store.operation === 'restore' ? 'Validando e restaurando…' : 'Confirmar restore'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </main>;
}
