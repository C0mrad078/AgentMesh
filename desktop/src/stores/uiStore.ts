import { create } from "zustand";
import type { TaskMode } from "@/types";

export type AppPage = "workspace" | "executions" | "agents" | "settings" | "learning";

interface UiState {
  activePage: AppPage;
  setActivePage: (page: AppPage) => void;
  newProjectDialogOpen: boolean;
  setNewProjectDialogOpen: (open: boolean) => void;
  selectedMode: TaskMode;
  setSelectedMode: (mode: TaskMode) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activePage: "workspace",
  setActivePage: (page) => set({ activePage: page }),
  newProjectDialogOpen: false,
  setNewProjectDialogOpen: (open) => set({ newProjectDialogOpen: open }),
  selectedMode: "automatic",
  setSelectedMode: (mode) => set({ selectedMode: mode }),
}));
