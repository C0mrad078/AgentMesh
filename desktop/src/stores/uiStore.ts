import { create } from "zustand";
import type { TaskMode } from "@/types";

// V3: collaboration is operational; Pixel Office remains a secondary view.
export type AppPage =
  | "collaboration" | "office" | "projects" | "team" | "workspace" | "executions"
  | "delivery" | "memory" | "providers" | "runtime-bindings" | "learning" | "settings";

interface UiState {
  activePage: AppPage;
  deliveryCandidateId: string | null;
  openDelivery: (id?: string) => void;
  syncLocation: () => void;
  setActivePage: (page: AppPage) => void;
  newProjectDialogOpen: boolean;
  setNewProjectDialogOpen: (open: boolean) => void;
  selectedMode: TaskMode;
  setSelectedMode: (mode: TaskMode) => void;
  selectedAgentIds: string[];
  setSelectedAgentIds: (ids: string[]) => void;
}

function deliveryLocation() {
  const match = window.location.pathname.match(/^\/delivery(?:\/([^/]+))?\/?$/);
  if (!match) return null;
  try { return { id: match[1] ? decodeURIComponent(match[1]) : null }; }
  catch { return { id: null }; }
}

export const useUiStore = create<UiState>((set) => ({
  activePage: deliveryLocation() ? "delivery" : "collaboration",
  deliveryCandidateId: deliveryLocation()?.id ?? null,
  openDelivery: (id) => {
    window.history.pushState({}, '', id ? `/delivery/${encodeURIComponent(id)}` : '/delivery');
    set({ activePage: 'delivery', deliveryCandidateId: id ?? null });
  },
  syncLocation: () => {
    const route = deliveryLocation();
    set({ activePage: route ? 'delivery' : 'collaboration', deliveryCandidateId: route?.id ?? null });
  },
  setActivePage: (page) => {
    if (page === 'delivery') window.history.pushState({}, '', '/delivery');
    else if (deliveryLocation()) window.history.pushState({}, '', '/');
    set({ activePage: page, deliveryCandidateId: null });
  },
  newProjectDialogOpen: false,
  setNewProjectDialogOpen: (open) => set({ newProjectDialogOpen: open }),
  selectedMode: "automatic",
  // Changing mode invalidates whatever agent selection was made for the
  // previous mode (a debate roster doesn't carry over to pipeline order).
  setSelectedMode: (mode) => set({ selectedMode: mode, selectedAgentIds: [] }),
  selectedAgentIds: [],
  setSelectedAgentIds: (ids) => set({ selectedAgentIds: ids }),
}));
