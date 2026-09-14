import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { useProjectsStore } from "@/stores/projectsStore";
import { useUiStore } from "@/stores/uiStore";
import type { Project } from "@/types";

function project(overrides: Partial<Project> = {}): Project {
  return {
    id: "proj_1",
    name: "AgentMash",
    description: "Core product",
    workspace_path: "/Users/dev/agentmash",
    status: "active",
    config: {},
    created_at: "now",
    updated_at: "now",
    ...overrides,
  };
}

describe("ProjectsPage", () => {
  beforeEach(() => {
    useProjectsStore.setState({ projects: [], selectedProjectId: null, loaded: true, loading: false, error: null });
    useUiStore.setState({ activePage: "projects" });
  });

  it("shows an empty state with a call to action when there are no projects", () => {
    render(<ProjectsPage />);
    expect(screen.getByText("Nenhum projeto ainda")).toBeInTheDocument();
  });

  it("shows a retry action when loading projects failed", () => {
    // `loaded: true` here so the page's own "fetch once on mount" effect
    // doesn't immediately overwrite this deliberately-set error state with
    // a real (unmocked) network call.
    useProjectsStore.setState({ loaded: true, loading: false, error: "network unreachable" });
    render(<ProjectsPage />);
    expect(screen.getByText(/Falha ao carregar projetos/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
  });

  it("lists real projects with their workspace path", () => {
    useProjectsStore.setState({ projects: [project()] });
    render(<ProjectsPage />);
    expect(screen.getByText("AgentMash")).toBeInTheDocument();
    expect(screen.getByText("/Users/dev/agentmash")).toBeInTheDocument();
  });

  it("entering the office selects the project and navigates to Office", async () => {
    useProjectsStore.setState({ projects: [project()] });
    render(<ProjectsPage />);

    await userEvent.click(screen.getByRole("button", { name: "Abrir Office" }));

    expect(useProjectsStore.getState().selectedProjectId).toBe("proj_1");
    expect(useUiStore.getState().activePage).toBe("office");
  });

  it("opens the new project dialog", async () => {
    render(<ProjectsPage />);
    // Both the header action and the empty-state's own call-to-action open
    // the same dialog when there are no projects yet -- either one proves it.
    const [firstNewProjectButton] = screen.getAllByRole("button", { name: "Novo projeto" });
    await userEvent.click(firstNewProjectButton);
    expect(useUiStore.getState().newProjectDialogOpen).toBe(true);
  });
});
