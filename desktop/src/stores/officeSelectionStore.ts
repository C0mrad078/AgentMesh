import { create } from "zustand";

export type OfficeViewMode = "project" | "all";

interface OfficeSelectionState {
  /** "project": only the currently-selected project (`projectsStore.selectedProjectId`).
   * "all": every project's agents at once (AgentMash V2 Phase 4 "MULTIPROJECT VIEW"). */
  viewMode: OfficeViewMode;
  setViewMode: (mode: OfficeViewMode) => void;
}

/** Deliberately its own small store, not folded into `uiStore` or
 * `projectsStore` -- the brief explicitly warns against one monolithic
 * frontend store ("Evite criar uma store global monolítica gigante"). */
export const useOfficeSelectionStore = create<OfficeSelectionState>((set) => ({
  viewMode: "project",
  setViewMode: (mode) => set({ viewMode: mode }),
}));
