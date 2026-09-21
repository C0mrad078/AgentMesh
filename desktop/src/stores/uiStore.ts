import { create } from "zustand";
import type { TaskMode } from "@/types";

// V3: collaboration is operational; Pixel Office remains a secondary view.
export type AppPage =
  | "collaboration" | "office" | "projects" | "team" | "workspace" | "executions"
  | "delivery" | "deployment" | "memory" | "providers" | "runtime-bindings" | "learning" | "settings";

interface UiState {
  activePage: AppPage;
  deliveryCandidateId: string | null;
  deploymentReleaseId: string | null;
  openDelivery: (id?: string) => void;
  openDeployment: (id?: string) => void;
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

function deploymentLocation() {
  const match = window.location.pathname.match(/^\/deployment(?:\/([^/]+))?\/?$/);
  if (!match) return null;
  try { return { id: match[1] ? decodeURIComponent(match[1]) : null }; }
  catch { return { id: null }; }
}

const initialDelivery = deliveryLocation();
const initialDeployment = deploymentLocation();

export const useUiStore = create<UiState>((set) => ({
  activePage: initialDeployment ? "deployment" : initialDelivery ? "delivery" : "collaboration",
  deliveryCandidateId: initialDelivery?.id ?? null,
  deploymentReleaseId: initialDeployment?.id ?? null,
  openDelivery: (id) => {
    window.history.pushState({}, '', id ? `/delivery/${encodeURIComponent(id)}` : '/delivery');
    set({ activePage: 'delivery', deliveryCandidateId: id ?? null, deploymentReleaseId: null });
  },
  openDeployment: (id) => {
    window.history.pushState({}, '', id ? `/deployment/${encodeURIComponent(id)}` : '/deployment');
    set({ activePage: 'deployment', deploymentReleaseId: id ?? null, deliveryCandidateId: null });
  },
  syncLocation: () => {
    const depRoute = deploymentLocation();
    if (depRoute) {
      set({ activePage: 'deployment', deploymentReleaseId: depRoute.id ?? null, deliveryCandidateId: null });
      return;
    }
    const delRoute = deliveryLocation();
    if (delRoute) {
      set({ activePage: 'delivery', deliveryCandidateId: delRoute.id ?? null, deploymentReleaseId: null });
      return;
    }
    set({ activePage: 'collaboration', deliveryCandidateId: null, deploymentReleaseId: null });
  },
  setActivePage: (page) => {
    if (page === 'delivery') window.history.pushState({}, '', '/delivery');
    else if (page === 'deployment') window.history.pushState({}, '', '/deployment');
    else if (deliveryLocation() || deploymentLocation()) window.history.pushState({}, '', '/');
    set({ activePage: page, deliveryCandidateId: null, deploymentReleaseId: null });
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
