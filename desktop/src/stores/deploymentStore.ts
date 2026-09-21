import { create } from 'zustand';
import { onBridgeEvent } from '@/services/bridge';
import { deploymentApi } from '@/services/deploymentApi';
import type { DeploymentEnvironmentSummary, DeploymentRecoveryStateDTO, DeploymentRunDetail, ReleaseCandidateDetail, ReleaseCandidateSummary } from '@/types/deployment';

interface DeploymentState {
  projectId: string | null;
  environments: DeploymentEnvironmentSummary[];
  releases: ReleaseCandidateSummary[];
  selectedReleaseId: string | null;
  detail: ReleaseCandidateDetail | null;
  runDetail: DeploymentRunDetail | null;
  recovery: DeploymentRecoveryStateDTO | null;
  loading: boolean;
  busy: boolean;
  error: string | null;
  liveEvent: string | null;
  load: (projectId: string) => Promise<void>;
  selectRelease: (releaseId: string | null) => Promise<void>;
  refresh: () => Promise<void>;
  execute: <T>(operation: () => Promise<T>, after?: () => Promise<void>) => Promise<T | null>;
  subscribe: () => () => void;
}

const topics = new Set([
  'deployment:release_created', 'deployment:predeploy_started', 'deployment:predeploy_completed',
  'deployment:approval_requested', 'deployment:approval_submitted', 'deployment:run_started',
  'deployment:run_updated', 'deployment:run_completed', 'deployment:run_failed',
  'deployment:health_check_started', 'deployment:health_check_completed', 'deployment:promotion_requested',
  'deployment:promotion_completed', 'deployment:rollback_proposed', 'deployment:rollback_started',
  'deployment:rollback_completed', 'deployment:lease_acquired', 'deployment:lease_released',
  'deployment:lease_expired', 'deployment:incident_created', 'deployment:incident_resolved',
]);
let loadToken = 0;
let refreshTask: Promise<void> | null = null;
let refreshAgain = false;

function message(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function matches(payload: Record<string, unknown>, state: DeploymentState): boolean {
  const projectId = payload.project_id;
  const releaseId = payload.release_candidate_id;
  return (!projectId || projectId === state.projectId) && (!releaseId || !state.selectedReleaseId || releaseId === state.selectedReleaseId);
}

function isRunDetail(value: unknown): value is DeploymentRunDetail {
  return typeof value === 'object' && value !== null && 'run' in value && 'attempts' in value && 'logs' in value;
}

export const useDeploymentStore = create<DeploymentState>()((set, get) => ({
  projectId: null, environments: [], releases: [], selectedReleaseId: null, detail: null, runDetail: null, recovery: null,
  loading: false, busy: false, error: null, liveEvent: null,
  load: async projectId => {
    const token = ++loadToken;
    set({ projectId, loading: true, error: null, detail: null, selectedReleaseId: null });
    try {
      const [environments, releases] = await Promise.all([deploymentApi.listEnvironments(projectId), deploymentApi.listReleases(projectId)]);
      if (token !== loadToken) return;
      set({ environments, releases, loading: false });
      if (releases[0]) await get().selectRelease(releases[0].id);
    } catch (error) { if (token === loadToken) set({ loading: false, error: message(error) }); }
  },
  selectRelease: async selectedReleaseId => {
    const projectId = get().projectId;
    set({ selectedReleaseId, detail: null, runDetail: null, error: null, loading: Boolean(selectedReleaseId) });
    if (!projectId || !selectedReleaseId) { set({ loading: false }); return; }
    try { const detail = await deploymentApi.getRelease(projectId, selectedReleaseId); set({ detail, recovery: detail.recovery, loading: false }); }
    catch (error) { set({ loading: false, error: message(error) }); }
  },
  refresh: async () => {
    if (refreshTask) { refreshAgain = true; return refreshTask; }
    const projectId = get().projectId;
    if (!projectId) return;
    refreshTask = (async () => {
      do {
        refreshAgain = false;
        try {
          const [environments, releases] = await Promise.all([deploymentApi.listEnvironments(projectId), deploymentApi.listReleases(projectId)]);
          set({ environments, releases, error: null });
          const id = get().selectedReleaseId;
          if (id) { const detail = await deploymentApi.getRelease(projectId, id); set({ detail, recovery: detail.recovery }); }
        } catch (error) { set({ error: message(error) }); }
      } while (refreshAgain);
    })();
    try { await refreshTask; } finally { refreshTask = null; }
  },
  execute: async (operation, after) => {
    if (get().busy) return null;
    set({ busy: true, error: null });
    try { const result = await operation(); if (isRunDetail(result)) set({ runDetail: result }); if (after) await after(); else await get().refresh(); return result; }
    catch (error) { set({ error: message(error) }); return null; }
    finally { set({ busy: false }); }
  },
  subscribe: () => {
    let disposed = false;
    let stop: (() => void) | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    void onBridgeEvent(event => {
      if (disposed || !topics.has(event.event)) return;
      const payload = event.payload as Record<string, unknown>;
      if (!matches(payload, get())) return;
      set({ liveEvent: event.event });
      if (!timer) timer = setTimeout(() => { timer = undefined; if (!disposed) void get().refresh(); }, 200);
    }).then(unlisten => { if (disposed) unlisten(); else stop = unlisten; }).catch(error => { if (!disposed) set({ error: message(error) }); });
    return () => { disposed = true; stop?.(); if (timer) clearTimeout(timer); };
  },
}));

export function deploymentOperationKey(releaseId: string, action: string, sha: string): string { return `deployment:${releaseId}:${sha}:${action}`; }
