import { beforeEach, describe, expect, it, vi } from 'vitest';
import { missionsApi } from '../api';
import { useMissionStore } from '../store';
import { snapshot } from './fixtures';
vi.mock('../api', () => ({ missionsApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), command: vi.fn() } }));
beforeEach(() => {
  vi.clearAllMocks();
  useMissionStore.setState({ projectId: null, selectedId: null, missions: [], snapshot: null, sending: false, error: null, loading: false });
  vi.mocked(missionsApi.list).mockResolvedValue([snapshot.mission]);
  vi.mocked(missionsApi.get).mockResolvedValue(snapshot);
});
describe('mission store', () => {
  it('restores mission from backend on project load', async () => {
    await useMissionStore.getState().load('project-1');
    expect(useMissionStore.getState().snapshot).toEqual(snapshot);
  });
  it('ignores duplicate events and refreshes a new persisted revision', async () => {
    await useMissionStore.getState().load('project-1');
    vi.mocked(missionsApi.get).mockClear();
    await useMissionStore.getState().event(snapshot.events[0]);
    expect(missionsApi.get).not.toHaveBeenCalled();
    await useMissionStore.getState().event({ ...snapshot.events[0], sequence: 2 });
    expect(missionsApi.get).toHaveBeenCalledWith('mission-1');
  });
  it('sends additional instruction without creating another mission', async () => {
    await useMissionStore.getState().load('project-1');
    await useMissionStore.getState().command({ action: 'instruction', content: 'Keep compatibility' });
    expect(missionsApi.command).toHaveBeenCalledWith('mission-1', { action: 'instruction', content: 'Keep compatibility' }, expect.any(String));
    expect(missionsApi.create).not.toHaveBeenCalled();
  });
  it('retains explicit backend error without fabricating success', async () => {
    await useMissionStore.getState().load('project-1');
    vi.mocked(missionsApi.command).mockRejectedValueOnce(new Error('CLI quota exhausted'));
    await useMissionStore.getState().command({ action: 'start' });
    expect(useMissionStore.getState().error).toBe('CLI quota exhausted');
    expect(useMissionStore.getState().snapshot?.mission.status).toBe('planned');
  });
  it('does not replace a newer selected mission with a stale response', async () => {
    let resolveOld: (value: typeof snapshot) => void = () => undefined;
    vi.mocked(missionsApi.get).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const old = useMissionStore.getState().select('old');
    await useMissionStore.getState().select('mission-1');
    resolveOld({ ...snapshot, mission: { ...snapshot.mission, id: 'old' } });
    await old;
    expect(useMissionStore.getState().snapshot?.mission.id).toBe('mission-1');
  });
});
