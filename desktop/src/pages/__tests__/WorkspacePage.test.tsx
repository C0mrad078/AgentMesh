import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { WorkspacePage } from "@/pages/WorkspacePage";
import { useProjectsStore } from "@/stores/projectsStore";
import { useExecutionStore } from "@/stores/executionStore";

describe("WorkspacePage", () => {
  beforeEach(() => {
    useProjectsStore.setState({ projects: [], selectedProjectId: null, loaded: true, loading: false, error: null });
    useExecutionStore.setState({
      activeTaskId: null,
      activeExecutionId: null,
      phases: [],
      task: null,
      submitting: false,
      error: null,
    });
  });

  it("shows an empty state when no project is selected", () => {
    render(<WorkspacePage />);
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    expect(screen.getByText("Nenhum projeto selecionado")).toBeInTheDocument();
  });

  it("shows the task form once a project is selected", () => {
    useProjectsStore.setState({
      projects: [
        {
          id: "proj_1",
          name: "Demo",
          description: "",
          workspace_path: null,
          status: "active",
          config: {},
          created_at: "now",
          updated_at: "now",
        },
      ],
      selectedProjectId: "proj_1",
    });

    render(<WorkspacePage />);
    expect(screen.getByText("Nova tarefa")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  });
});
