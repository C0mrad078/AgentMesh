/** Wire DTOs follow core/reliability/models.py and the M6 shared contract. */
export interface BackupManifestDTO {
  backup_id: string;
  schema_version: number;
  app_version: string;
  created_at: string;
  db_size_bytes: number;
  sha256: string;
  source_path: string;
  tables_count: number;
  records_summary: Record<string, number>;
  protected: boolean;
}

export interface BackupInfoDTO { manifest: BackupManifestDTO; database_path: string; manifest_path: string; }
export interface RestoreResultDTO { backup_id: string; restored_path: string; safety_snapshot_path: string; schema_version: number; }
export interface RecoveryIssueDTO { code: string; message: string; path: string | null; details: Record<string, unknown>; }

export interface DiagnosticsMetadataDTO {
  app_version: string; os: string; platform: string; architecture: string; python_version: string;
  node_version: string | null; applied_migrations: number[]; memory_usage_bytes: number | null; uptime_seconds: number;
}
export interface DiagnosticsProviderDTO { name: string; available?: boolean; version?: string; }
export interface DiagnosticsRuntimeBindingDTO { provider?: string; health?: string; configured_capacity?: number; observed_capacity?: number; reserved_slots?: number; target_branch?: string; }
export interface DiagnosticsDatabaseHealthDTO { file_size_bytes: number; pragmas: Record<string, string | number | boolean | null>; tables_count: number; records_summary: Record<string, number>; }
export interface DiagnosticsReportDTO { metadata: DiagnosticsMetadataDTO; providers: DiagnosticsProviderDTO[]; runtime_bindings: DiagnosticsRuntimeBindingDTO[]; database_health: DiagnosticsDatabaseHealthDTO; logs_sanitized: string[]; }

/** The shared contract does not define this response payload yet. */
export type OnboardingStatusDTO = unknown;
/** The shared contract defines the export operation but not its bridge result shape. */
export type DiagnosticsExportDTO = unknown;
export type ReliabilityOperation = 'diagnostics' | 'export' | 'backup-create' | 'backup-list' | 'restore' | 'onboarding';

export function isDiagnosticsReport(value: unknown): value is DiagnosticsReportDTO {
  if (typeof value !== 'object' || value === null) return false;
  const report = value as Partial<DiagnosticsReportDTO>;
  return typeof report.metadata === 'object' && report.metadata !== null
    && typeof report.database_health === 'object' && report.database_health !== null
    && Array.isArray(report.providers) && Array.isArray(report.runtime_bindings)
    && Array.isArray(report.logs_sanitized);
}

export function isBackupInfo(value: unknown): value is BackupInfoDTO {
  if (typeof value !== 'object' || value === null || !('manifest' in value)) return false;
  const manifest = (value as { manifest: unknown }).manifest;
  return typeof manifest === 'object' && manifest !== null && 'backup_id' in manifest && 'sha256' in manifest;
}

export function backupInfoFrom(value: unknown): BackupInfoDTO | null {
  if (isBackupInfo(value)) return value;
  if (typeof value === 'object' && value !== null && 'backup_id' in value && 'sha256' in value) {
    return { manifest: value as BackupManifestDTO, database_path: '', manifest_path: '' };
  }
  return null;
}
