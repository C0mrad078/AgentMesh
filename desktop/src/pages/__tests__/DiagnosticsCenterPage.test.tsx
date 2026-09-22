import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DiagnosticsCenterPage } from '@/pages/DiagnosticsCenterPage';
import type { BackupInfoDTO, DiagnosticsReportDTO } from '@/types/reliability';

const { store } = vi.hoisted(() => ({ store: { diagnostics: null as DiagnosticsReportDTO | null, backups: [] as BackupInfoDTO[], onboarding: null as unknown, restoreResult: null as { backup_id: string; restored_path: string; safety_snapshot_path: string; schema_version: number } | null, exportResult: null as unknown, loading: false, operation: null as string | null, progress: null as string | null, errors: {} as Record<string, string | undefined>, loadDiagnostics: vi.fn(), loadBackups: vi.fn(), loadOnboarding: vi.fn(), refresh: vi.fn(), createBackup: vi.fn(), exportDiagnostics: vi.fn(), restoreBackup: vi.fn() } }));
vi.mock('@/stores/reliabilityStore', () => ({ useReliabilityStore: (selector?: (state: typeof store) => unknown) => selector ? selector(store) : store }));

const report: DiagnosticsReportDTO = {
  metadata: { app_version: '0.1.0-rc.1', os: 'Linux', platform: 'Linux test', architecture: 'x64', python_version: '3.12', node_version: '22', applied_migrations: [1, 2, 21], memory_usage_bytes: null, uptime_seconds: 90 },
  providers: [{ name: 'git', available: true, version: '2.4' }],
  runtime_bindings: [{ provider: 'codex_cli', health: 'healthy', configured_capacity: 2, observed_capacity: 2, reserved_slots: 1 }],
  database_health: { file_size_bytes: 4096, pragmas: { integrity_check: 'ok', journal_mode: 'wal' }, tables_count: 19, records_summary: { missions: 2 } },
  logs_sanitized: ['2026-09-21 INFO safe_event'],
};
const backup: BackupInfoDTO = { manifest: { backup_id: 'bkp-test', schema_version: 21, app_version: '0.1.0-rc.1', created_at: '2026-09-21T12:00:00Z', db_size_bytes: 1024, sha256: 'a'.repeat(64), source_path: '/private/user/db.sqlite', tables_count: 19, records_summary: { missions: 2 }, protected: true }, database_path: '', manifest_path: '' };
beforeEach(() => { vi.clearAllMocks(); Object.assign(store, { diagnostics: report, backups: [backup], onboarding: null, restoreResult: null, exportResult: null, loading: false, operation: null, progress: null, errors: {} }); });
afterEach(cleanup);

describe('DiagnosticsCenterPage', () => {
  it('shows RC version, SQLite health, providers, applied migrations, and sanitized logs', () => {
    render(<DiagnosticsCenterPage />);
    expect(screen.getByText('0.1.0-rc.1')).toBeInTheDocument();
    expect(screen.getByText('ok')).toBeInTheDocument();
    expect(screen.getByText('git · 2.4')).toBeInTheDocument();
    expect(screen.getByText('3 migration(s) reportada(s).')).toBeInTheDocument();
    expect(screen.getByLabelText('Logs sanitizados')).toHaveTextContent('safe_event');
    expect(screen.queryByText('/private/user/db.sqlite')).not.toBeInTheDocument();
  });

  it('renders a clean first-use empty state and retries failed diagnostics', async () => {
    store.diagnostics = null; store.backups = []; store.errors = { diagnostics: 'Database is locked' };
    render(<DiagnosticsCenterPage />);
    expect(screen.getByText('Nenhum backup disponível.')).toBeInTheDocument();
    expect(screen.getAllByRole('alert').some(element => element.textContent?.includes('Database is locked'))).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'Atualizar' }));
    expect(store.refresh).toHaveBeenCalledTimes(2); // initial page load + explicit retry
  });

  it('requires explicit confirmation before invoking restore and shows safety snapshot only after response', async () => {
    store.restoreBackup.mockImplementation(async () => {
      store.restoreResult = { backup_id: 'bkp-test', restored_path: '/safe/db', safety_snapshot_path: '/safe/pre-restore.db', schema_version: 21 };
      return true;
    });
    render(<DiagnosticsCenterPage />);
    await userEvent.click(screen.getByRole('button', { name: 'Restaurar…' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/conteúdo atual do banco será substituído/i)).toBeInTheDocument();
    const confirm = within(dialog).getByRole('button', { name: 'Confirmar restore' });
    expect(confirm).toBeDisabled();
    await userEvent.click(within(dialog).getByRole('checkbox'));
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(store.restoreBackup).toHaveBeenCalledWith('bkp-test'));
    expect(await screen.findByText(/Safety snapshot criado/)).toBeInTheDocument();
  });

  it('does not claim an export path when the bridge returns an unspecified payload', async () => {
    store.exportResult = { result: 'ok' };
    render(<DiagnosticsCenterPage />);
    fireEvent.click(screen.getByRole('button', { name: /Exportar diagnostics bundle/ }));
    expect(screen.getAllByRole('status').some(element => element.textContent?.includes('caminho de saída não foi definido no contrato'))).toBe(true);
  });
});
