import { create } from "zustand";
import { projectsApi } from "@/services/api";
import type { Project } from "@/types";

interface ProjectsState {
  projects: Project[];
  selectedProjectId: string | null;
  loading: boolean;
  error: string | null;
  loaded: boolean;
  loadProjects: () => Promise<void>;
  createProject: (input: { name: string; description?: string; workspace_path?: string }) => Promise<Project>;
  selectProject: (projectId: string | null) => void;
}

export const useProjectsStore = create<ProjectsState>((set) => ({
  projects: [],
  selectedProjectId: null,
  loading: false,
  error: null,
  loaded: false,

  loadProjects: async () => {
    set({ loading: true, error: null });
    try {
      const projects = await projectsApi.list();
      set((state) => ({
        projects,
        loading: false,
        loaded: true,
        selectedProjectId: state.selectedProjectId ?? projects[0]?.id ?? null,
      }));
    } catch (error) {
      set({ loading: false, error: error instanceof Error ? error.message : String(error) });
    }
  },

  createProject: async (input) => {
    const project = await projectsApi.create(input);
    set((state) => ({
      projects: [project, ...state.projects],
      selectedProjectId: project.id,
    }));
    return project;
  },

  selectProject: (projectId) => set({ selectedProjectId: projectId }),
}));

export function useSelectedProject(): Project | null {
  const { projects, selectedProjectId } = useProjectsStore();
  return projects.find((p) => p.id === selectedProjectId) ?? null;
}
