import { create } from 'zustand';
import { deliveryApi } from '@/services/deliveryApi';
import { onBridgeEvent } from '@/services/bridge';
import { safeText } from '@/components/delivery/presentation';
import type { DeliveryCandidateDetail, DeliveryCandidateSummary } from '@/types/delivery';
interface DeliveryState {
  candidates: DeliveryCandidateSummary[]; detail: DeliveryCandidateDetail | null; selectedId: string | null;
  loading: boolean; listLoading: boolean; busy: boolean; error: string | null; progress: string | null;
  load: () => Promise<void>; select: (id: string | null) => Promise<void>; refresh: () => Promise<void>;
  run: (operation: () => Promise<unknown>) => Promise<boolean>; subscribe: () => () => void;
}
let selection = 0;
let detailRequest = 0;
let listRequest = 0;
let refreshTask: Promise<void> | null = null;
let refreshAgain = false;
export const useDeliveryStore = create<DeliveryState>()((set, get) => ({
  candidates: [], detail: null, selectedId: null, loading: false, listLoading: false, busy: false, error: null, progress: null,
  load: async () => {
    const request = ++listRequest;
    set({ listLoading: true, error: null });
    try { const candidates = await deliveryApi.list(); if (request === listRequest) set({ candidates }); }
    catch (e) { if (request === listRequest) set({ error: safeText(e instanceof Error ? e.message : e) }); }
    finally { if (request === listRequest) set({ listLoading: false }); }
  },
  select: async id => {
    const token = ++selection;
    const request = ++detailRequest;
    set({ selectedId: id, detail: null, loading: !!id, error: null, progress: null });
    if (!id) return;
    try { const detail = await deliveryApi.get(id); if (token === selection && request === detailRequest) set({ detail }); }
    catch (e) { if (token === selection && request === detailRequest) set({ error: safeText(e instanceof Error ? e.message : e) }); }
    finally { if (token === selection && request === detailRequest) set({ loading: false }); }
  },
  refresh: async () => {
    if (refreshTask) { refreshAgain = true; return refreshTask; }
    refreshTask = (async () => {
      do {
        refreshAgain = false;
        const token = selection;
        const request = ++detailRequest;
        const listToken = ++listRequest;
        const id = get().selectedId;
        try {
          const [candidates, detail] = await Promise.all([deliveryApi.list(), id ? deliveryApi.get(id) : Promise.resolve(null)]);
          if (listToken === listRequest) set({ candidates, listLoading: false });
          if (token === selection && request === detailRequest) set({ detail, error: null, loading: false });
        } catch (e) { if (token === selection && request === detailRequest) set({ error: safeText(e instanceof Error ? e.message : e), loading: false }); }
        finally { if (listToken === listRequest) set({ listLoading: false }); }
      } while (refreshAgain);
    })();
    try { await refreshTask; } finally { refreshTask = null; }
  },
  run: async operation => {
    if (get().busy) return false;
    set({ busy: true, error: null });
    try { await operation(); await get().refresh(); return !get().error; }
    catch (e) { set({ error: safeText(e instanceof Error ? e.message : e) }); return false; }
    finally { set({ busy: false }); }
  },
  subscribe: () => {
    let disposed = false;
    let stop: (() => void) | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    void onBridgeEvent(event => {
      if (disposed) return;
      if (!['delivery.candidate_updated', 'delivery.preflight_progress', 'delivery.ci_updated', 'delivery.operation_progress'].includes(event.event)) return;
      const payload = event.payload as Record<string, unknown>;
      if (payload.candidate_id === get().selectedId) set({ progress: safeText([payload.step, payload.status].filter(Boolean).join(' · ')) });
      if (!timer) timer = setTimeout(() => { timer = undefined; if (!disposed) void get().refresh(); }, 200);
    }).then(fn => { if (disposed) fn(); else stop = fn; }).catch(() => {
      if (!disposed) set({ error: 'Não foi possível acompanhar eventos. Atualize para recuperar o estado persistido.' });
    });
    return () => { disposed = true; stop?.(); if (timer) clearTimeout(timer); };
  },
}));
/** Stable across retries/restarts; version and approved SHA identify the reviewed payload. */
export function operationKey(detail: DeliveryCandidateDetail, action: string): string {
  return `delivery:${detail.candidate.id}:v${detail.candidate.version}:${action}:${detail.pull_request?.head_sha ?? detail.snapshot.integration_sha}`;
}
