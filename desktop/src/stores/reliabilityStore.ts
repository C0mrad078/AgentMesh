import { create } from 'zustand';
import { reliabilityApi } from '@/services/reliabilityApi';
import { backupInfoFrom, isDiagnosticsReport } from '@/types/reliability';
import type { BackupInfoDTO, DiagnosticsExportDTO, DiagnosticsReportDTO, OnboardingStatusDTO, ReliabilityOperation, RestoreResultDTO } from '@/types/reliability';

interface ReliabilityState {
  diagnostics: DiagnosticsReportDTO | null;
  backups: BackupInfoDTO[];
  onboarding: OnboardingStatusDTO | null;
  restoreResult: RestoreResultDTO | null;
  exportResult: DiagnosticsExportDTO | null;
  loading: boolean;
  operation: ReliabilityOperation | null;
  progress: string | null;
  errors: Partial<Record<'diagnostics' | 'backups' | 'onboarding' | 'operation', string>>;
  loadDiagnostics: () => Promise<void>;
  loadBackups: () => Promise<void>;
  loadOnboarding: () => Promise<void>;
  refresh: () => Promise<void>;
  createBackup: (protectedBackup?: boolean) => Promise<BackupInfoDTO | null>;
  exportDiagnostics: () => Promise<DiagnosticsExportDTO | null>;
  restoreBackup: (backupId: string) => Promise<RestoreResultDTO | null>;
}

function safeError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  return raw.replace(/(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{8,}/g, '[redacted]')
    .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/(?:[A-Za-z]:\\|\/Users\/|\/home\/)[^\s]+/g, '[path redacted]')
    .replace(/(authorization|cookie|x-api-key|password|secret|token)\s*[:=]\s*[^\s,;]+/gi, '$1=[redacted]')
    .slice(0, 500);
}

let diagnosticsRequest = 0;
let backupsRequest = 0;
let operationLock = false;

export const useReliabilityStore = create<ReliabilityState>()((set, get) => ({
  diagnostics: null, backups: [], onboarding: null, restoreResult: null, exportResult: null,
  loading: false, operation: null, progress: null, errors: {},
  loadDiagnostics: async () => {
    const request = ++diagnosticsRequest;
    set(state => ({ loading: true, errors: { ...state.errors, diagnostics: undefined } }));
    try {
      const report: unknown = await reliabilityApi.collectDiagnostics();
      if (request !== diagnosticsRequest) return;
      if (!isDiagnosticsReport(report)) throw new Error('O bridge retornou um relatório de diagnóstico incompatível.');
      set({ diagnostics: report });
    } catch (error) { if (request === diagnosticsRequest) set(state => ({ errors: { ...state.errors, diagnostics: safeError(error) } })); }
    finally { if (request === diagnosticsRequest) set({ loading: false }); }
  },
  loadBackups: async () => {
    const request = ++backupsRequest;
    set(state => ({ errors: { ...state.errors, backups: undefined } }));
    try {
      const rows: unknown = await reliabilityApi.listBackups();
      if (request !== backupsRequest) return;
      if (!Array.isArray(rows)) throw new Error('O bridge retornou uma lista de backups incompatível.');
      const backups = rows.map(backupInfoFrom).filter((row): row is BackupInfoDTO => row !== null);
      set({ backups });
    } catch (error) { if (request === backupsRequest) set(state => ({ errors: { ...state.errors, backups: safeError(error) } })); }
  },
  loadOnboarding: async () => {
    set(state => ({ errors: { ...state.errors, onboarding: undefined } }));
    try { const onboarding = await reliabilityApi.onboardingStatus(); set({ onboarding }); }
    catch (error) { set(state => ({ errors: { ...state.errors, onboarding: safeError(error) } })); }
  },
  refresh: async () => { await Promise.all([get().loadDiagnostics(), get().loadBackups(), get().loadOnboarding()]); },
  createBackup: async (protectedBackup = false) => {
    if (operationLock) return null;
    operationLock = true;
    set({ operation: 'backup-create', progress: 'Criando snapshot consistente do banco…', restoreResult: null, errors: { ...get().errors, operation: undefined } });
    try {
      const raw: unknown = await reliabilityApi.createBackup(protectedBackup);
      const info = backupInfoFrom(raw);
      if (!info) throw new Error('O bridge não confirmou os metadados do backup.');
      set({ backups: [info, ...get().backups.filter(item => item.manifest.backup_id !== info.manifest.backup_id)], progress: 'Backup confirmado pelo backend.' });
      return info;
    } catch (error) { set(state => ({ errors: { ...state.errors, operation: safeError(error) }, progress: null })); return null; }
    finally { operationLock = false; set({ operation: null }); }
  },
  exportDiagnostics: async () => {
    if (operationLock) return null;
    operationLock = true;
    set({ operation: 'export', progress: 'Gerando e sanitizando o diagnostics bundle…', exportResult: null, errors: { ...get().errors, operation: undefined } });
    try { const result = await reliabilityApi.exportDiagnostics(); set({ exportResult: result, progress: 'Exportação concluída pelo backend.' }); return result; }
    catch (error) { set(state => ({ errors: { ...state.errors, operation: safeError(error) }, progress: null })); return null; }
    finally { operationLock = false; set({ operation: null }); }
  },
  restoreBackup: async backupId => {
    if (operationLock) return null;
    operationLock = true;
    set({ operation: 'restore', progress: 'O backend está validando integridade e compatibilidade antes do restore…', restoreResult: null, errors: { ...get().errors, operation: undefined } });
    try {
      const result = await reliabilityApi.restoreBackup(backupId);
      set({ restoreResult: result, progress: 'Restore e verificação confirmados pelo backend.' });
      await get().loadDiagnostics();
      return result;
    } catch (error) { set(state => ({ errors: { ...state.errors, operation: safeError(error) }, progress: 'Restore não confirmado. Consulte o diagnóstico do banco e a mensagem de recuperação do backend.' })); return null; }
    finally { operationLock = false; set({ operation: null }); }
  },
}));
