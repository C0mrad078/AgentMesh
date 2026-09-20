import { create } from "zustand";
import type { TaskMode } from "@/types";

// V3: collaboration is operational; Pixel Office remains a secondary view.
export type AppPage =
  | "collaboration" | "office" | "projects" | "team" | "workspace" | "executions"
  | "memory" | "providers" | "learning" | "settings";

interface UiState {
  activePage: AppPage;
  setActivePage: (page: AppPage) => void;
  newProjectDialogOpen: boolean;
  setNewProjectDialogOpen: (open: boolean) => void;
  selectedMode: TaskMode;
  setSelectedMode: (mode: TaskMode) => void;
  selectedAgentIds: string[];
  setSelectedAgentIds: (ids: string[]) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activePage: "collaboration",
  setActivePage: (page) => set({ activePage: page }),
  newProjectDialogOpen: false,
  setNewProjectDialogOpen: (open) => set({ newProjectDialogOpen: open }),
  selectedMode: "automatic",
  // Changing mode invalidates whatever agent selection was made for the
  // previous mode (a debate roster doesn't carry over to pipeline order).
  setSelectedMode: (mode) => set({ selectedMode: mode, selectedAgentIds: [] }),
  selectedAgentIds: [],
  setSelectedAgentIds: (ids) => set({ selectedAgentIds: ids }),
}));
