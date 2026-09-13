import { create } from "zustand";
import type { TaskMode } from "@/types";

export type AppPage = "office" | "workspace" | "executions" | "agents" | "settings" | "learning";

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
  // Virtual Office is the new default landing page (spec section 4) --
  // Workspace ("Classic Dashboard") remains one click away and fully
  // functional (spec section 34: the Office is never mandatory).
  activePage: "office",
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
