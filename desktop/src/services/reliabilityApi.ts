import { invokeBridge } from '@/services/bridge';
import type { BackupInfoDTO, DiagnosticsExportDTO, DiagnosticsReportDTO, OnboardingStatusDTO, RestoreResultDTO } from '@/types/reliability';

/** Only the six commands defined by the M6 contract are invoked here. */
export const reliabilityApi = {
  collectDiagnostics: () => invokeBridge<DiagnosticsReportDTO>('system.diagnostics.collect'),
  exportDiagnostics: () => invokeBridge<DiagnosticsExportDTO>('system.diagnostics.export'),
  createBackup: (protectedBackup = false) => invokeBridge<BackupInfoDTO>('system.backup.create', protectedBackup ? { protected: true } : {}),
  listBackups: () => invokeBridge<BackupInfoDTO[]>('system.backup.list'),
  restoreBackup: (backup_id: string) => invokeBridge<RestoreResultDTO>('system.backup.restore', { backup_id }),
  onboardingStatus: () => invokeBridge<OnboardingStatusDTO>('system.onboarding.status'),
};
