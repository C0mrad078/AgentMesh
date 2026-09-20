import { create } from 'zustand';
import { missionsApi } from './api';
import type { CommandInput, Mission, MissionEvent, MissionSnapshot } from './types';
interface MissionState {
  projectId: string | null; missions: Mission[]; selectedId: string | null;
  snapshot: MissionSnapshot | null; loading: boolean; sending: boolean; error: string | null;
  load: (projectId: string) => Promise<void>; select: (id: string) => Promise<void>;
  refresh: () => Promise<void>; event: (event: MissionEvent) => Promise<void>;
  submit: (request: string) => Promise<void>; command: (input: CommandInput) => Promise<void>;
}
let generation = 0;
let refreshing: Promise<void> | null = null;
let refreshAgain = false;
const message = (error: unknown) => error instanceof Error ? error.message : String(error);
export const useMissionStore = create<MissionState>((set, get) => ({
  projectId: null, missions: [], selectedId: null, snapshot: null, loading: false, sending: false, error: null,
  load: async (projectId) => {
    const current = ++generation;
    set({ projectId, selectedId: null, snapshot: null, missions: [], loading: true, error: null });
    try {
      const missions = await missionsApi.list(projectId);
      if (generation !== current) return;
      set({ missions, loading: false });
      if (missions[0]) await get().select(missions[0].id);
    } catch (error) { if (generation === current) set({ error: message(error), loading: false }); }
  },
  select: async (id) => {
    const current = ++generation;
    set({ selectedId: id, snapshot: null, loading: true, error: null });
    try {
      const snapshot = await missionsApi.get(id);
      if (generation === current) set({ snapshot, loading: false });
    } catch (error) { if (generation === current) set({ error: message(error), loading: false }); }
  },
  refresh: async () => {
    if (refreshing) { refreshAgain = true; return refreshing; }
    refreshing = (async () => {
      do {
        refreshAgain = false;
        const { projectId, selectedId } = get();
        const current = generation;
        if (!projectId) return;
        try {
          const [missions, snapshot] = await Promise.all([
            missionsApi.list(projectId), selectedId ? missionsApi.get(selectedId) : Promise.resolve(null),
          ]);
          if (generation === current) set({ missions, snapshot, error: null });
        } catch (error) { if (generation === current) set({ error: message(error) }); }
      } while (refreshAgain);
    })();
    try { await refreshing; } finally { refreshing = null; }
  },
  event: async (event) => {
    const { snapshot, selectedId, missions } = get();
    if (event.mission_id !== selectedId && !missions.some(m => m.id === event.mission_id)) return;
    if (snapshot?.mission.id === event.mission_id && (snapshot.events.at(-1)?.sequence ?? 0) >= event.sequence) return;
    await get().refresh();
  },
  submit: async (request) => {
    const { projectId, sending } = get();
    if (!projectId || sending) return;
    set({ sending: true, error: null });
    try {
      const mission = await missionsApi.create(projectId, request, crypto.randomUUID());
      if (get().projectId !== projectId) return;
      await get().refresh();
      await get().select(mission.id);
      await missionsApi.command(mission.id, { action: 'analyze' }, crypto.randomUUID());
      await get().refresh();
    } catch (error) { set({ error: message(error) }); }
    finally { set({ sending: false }); }
  },
  command: async (input) => {
    const { selectedId, sending } = get();
    if (!selectedId || sending) return;
    set({ sending: true, error: null });
    try {
      await missionsApi.command(selectedId, input, crypto.randomUUID());
      await get().refresh();
    } catch (error) { set({ error: message(error) }); }
    finally { set({ sending: false }); }
  },
}));
