import { create } from "zustand";
import { sessionsApi } from "@/services/api";
import type { Session } from "@/types";

interface SessionsState {
  sessions: Session[];
  loading: boolean;
  loaded: boolean;
  error: string | null;
  /** No filter = every currently-active (non-terminal) session across
   * every project -- what the Office's domain adapter needs to derive
   * real presence. */
  loadSessions: () => Promise<void>;
}

/** AgentMash V2, Phase 4: real session data (`core.sessions`) for the
 * Office to derive WORKING/WAITING presence from -- empty and honest
 * ("No active session") until a real runtime (Phase 5+) creates one. */
export const useSessionsStore = create<SessionsState>((set) => ({
  sessions: [],
  loading: false,
  loaded: false,
  error: null,

  loadSessions: async () => {
    set({ loading: true, error: null });
    try {
      const sessions = await sessionsApi.list();
      set({ sessions, loading: false, loaded: true });
    } catch (error) {
      set({ loading: false, error: error instanceof Error ? error.message : String(error) });
    }
  },
}));
