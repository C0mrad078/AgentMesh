import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useDeliveryStore, operationKey } from '../deliveryStore';
import { deliveryApi } from '@/services/deliveryApi';
import { onBridgeEvent } from '@/services/bridge';
import { detail, summary } from '@/components/delivery/__tests__/fixtures';
import type { DeliveryCandidateDetail } from '@/types/delivery';
import type { OrchestratorEvent } from '@/types';
vi.mock('@/services/deliveryApi', () => ({ deliveryApi: { list: vi.fn(), get: vi.fn() } }));
vi.mock('@/services/bridge', () => ({ onBridgeEvent: vi.fn() }));
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { resolve, promise }; };
beforeEach(() => {
  vi.clearAllMocks();
  useDeliveryStore.setState({ candidates: [], detail: null, selectedId: null, loading: false, listLoading: false, busy: false, error: null, progress: null });
  vi.mocked(deliveryApi.list).mockResolvedValue([summary()]); vi.mocked(deliveryApi.get).mockResolvedValue(detail()); vi.mocked(onBridgeEvent).mockResolvedValue(vi.fn());
});
describe('Delivery store', () => {
  it('ignores a late candidate response after selection changes', async () => {
    const first = deferred<DeliveryCandidateDetail>(); vi.mocked(deliveryApi.get).mockReturnValueOnce(first.promise);
    const old = useDeliveryStore.getState().select('old');
    const next = detail(); next.candidate.id = 'new'; vi.mocked(deliveryApi.get).mockResolvedValueOnce(next);
    await useDeliveryStore.getState().select('new'); first.resolve(detail()); await old;
    expect(useDeliveryStore.getState().detail?.candidate.id).toBe('new');
  });
  it('does not clear candidate loading when the list finishes first', async () => {
    const candidate = deferred<DeliveryCandidateDetail>(); vi.mocked(deliveryApi.get).mockReturnValueOnce(candidate.promise);
    const list = useDeliveryStore.getState().load(); const selected = useDeliveryStore.getState().select('c'); await list;
    expect(useDeliveryStore.getState().loading).toBe(true); candidate.resolve(detail()); await selected;
    expect(useDeliveryStore.getState().loading).toBe(false);
  });
  it('does not let an older load overwrite a newer event refresh', async () => {
    const oldDetail = deferred<DeliveryCandidateDetail>();
    const oldList = deferred<ReturnType<typeof summary>[]>();
    vi.mocked(deliveryApi.get).mockReturnValueOnce(oldDetail.promise);
    vi.mocked(deliveryApi.list).mockReturnValueOnce(oldList.promise);
    const selected = useDeliveryStore.getState().select('candidate-1');
    const loaded = useDeliveryStore.getState().load();
    const newer = detail(); newer.candidate.version = 2;
    vi.mocked(deliveryApi.get).mockResolvedValueOnce(newer);
    vi.mocked(deliveryApi.list).mockResolvedValueOnce([summary(newer)]);
    await useDeliveryStore.getState().refresh();
    oldDetail.resolve(detail()); oldList.resolve([summary()]); await Promise.all([selected, loaded]);
    expect(useDeliveryStore.getState().detail?.candidate.version).toBe(2);
    expect(useDeliveryStore.getState().candidates[0].version).toBe(2);
    expect(useDeliveryStore.getState().loading).toBe(false);
  });
  it('serializes mutations and reloads authoritative state', async () => {
    const task = deferred<void>(); const first = vi.fn(() => task.promise); const duplicate = vi.fn();
    const pending = useDeliveryStore.getState().run(first); expect(await useDeliveryStore.getState().run(duplicate)).toBe(false);
    expect(duplicate).not.toHaveBeenCalled(); task.resolve(); expect(await pending).toBe(true); expect(deliveryApi.list).toHaveBeenCalledOnce();
  });
  it('coalesces delivery event bursts and unsubscribes on disposal', async () => {
    vi.useFakeTimers(); let listener!: (event: OrchestratorEvent) => void; const stop = vi.fn();
    vi.mocked(onBridgeEvent).mockImplementation(async callback => { listener = callback; return stop; });
    useDeliveryStore.setState({ selectedId: 'candidate-1' }); const dispose = useDeliveryStore.getState().subscribe(); await Promise.resolve();
    listener({ event: 'unrelated', payload: {} });
    for (const event of ['delivery.candidate_updated', 'delivery.preflight_progress', 'delivery.ci_updated', 'delivery.operation_progress']) listener({ event, payload: { candidate_id: 'candidate-1', status: 'running' } });
    await vi.advanceTimersByTimeAsync(200); expect(deliveryApi.list).toHaveBeenCalledOnce(); expect(deliveryApi.get).toHaveBeenCalledOnce();
    expect(useDeliveryStore.getState().progress).toBe('running'); dispose(); expect(stop).toHaveBeenCalledOnce(); vi.useRealTimers();
  });
  it('cleans a subscription that resolves after unmount', async () => {
    const registration = deferred<() => void>(); vi.mocked(onBridgeEvent).mockReturnValueOnce(registration.promise);
    const dispose = useDeliveryStore.getState().subscribe(); dispose(); const stop = vi.fn(); registration.resolve(stop); await Promise.resolve(); expect(stop).toHaveBeenCalledOnce();
  });
  it('reports subscription failure as recovery instead of an unhandled rejection', async () => {
    vi.mocked(onBridgeEvent).mockRejectedValueOnce(new Error('offline')); const dispose = useDeliveryStore.getState().subscribe(); await Promise.resolve(); await Promise.resolve();
    expect(useDeliveryStore.getState().error).toContain('acompanhar eventos'); dispose();
  });
  it('uses stable keys across retries and changes key for a new version/head', () => {
    const d = detail(); const key = operationKey(d, 'push'); expect(operationKey(d, 'push')).toBe(key); d.candidate.version++; expect(operationKey(d, 'push')).not.toBe(key);
  });
});
