import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sidebar } from "@/layouts/Sidebar";
import { useProjectsStore } from "@/stores/projectsStore";

describe("Sidebar", () => {
  it("shows a retry action when loading projects fails", () => {
    useProjectsStore.setState({
      projects: [],
      loading: false,
      loaded: true,
      error: "network unreachable",
    });

    render(<Sidebar />);

    expect(screen.getByText(/Falha ao carregar projetos/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
  });

  it("shows an empty-state message when there are no projects and no error", () => {
    useProjectsStore.setState({ projects: [], loading: false, loaded: true, error: null });

    render(<Sidebar />);

    expect(screen.getByText(/Nenhum projeto ainda/)).toBeInTheDocument();
  });

  it("lists projects once loaded", () => {
    useProjectsStore.setState({
      projects: [
        {
          id: "proj_1",
          name: "Demo Project",
          description: "",
          workspace_path: null,
          status: "active",
          config: {},
          created_at: "now",
          updated_at: "now",
        },
      ],
      loading: false,
      loaded: true,
      error: null,
    });

    render(<Sidebar />);

    expect(screen.getByText("Demo Project")).toBeInTheDocument();
  });
});
