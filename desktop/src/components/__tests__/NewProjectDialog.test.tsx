import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  projectsApi: {
    create: vi.fn(),
    list: vi.fn(),
  },
}));

import { projectsApi } from "@/services/api";
import { NewProjectDialog } from "@/components/NewProjectDialog";
import { useProjectsStore } from "@/stores/projectsStore";
import { useUiStore } from "@/stores/uiStore";

describe("NewProjectDialog", () => {
  beforeEach(() => {
    useUiStore.setState({ newProjectDialogOpen: true });
    useProjectsStore.setState({ projects: [], selectedProjectId: null, loaded: true, loading: false, error: null });
    vi.clearAllMocks();
  });

  it("creates a project and closes the dialog on submit", async () => {
    vi.mocked(projectsApi.create).mockResolvedValue({
      id: "proj_new",
      name: "My Project",
      description: "",
      workspace_path: null,
      status: "active",
      config: {},
      created_at: "now",
      updated_at: "now",
    });

    render(<NewProjectDialog />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Nome"), "My Project");
    await user.click(screen.getByRole("button", { name: "Criar projeto" }));

    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledWith({ name: "My Project", description: "" }));
    await waitFor(() => expect(useUiStore.getState().newProjectDialogOpen).toBe(false));
    expect(useProjectsStore.getState().selectedProjectId).toBe("proj_new");
  });

  it("shows a validation error when the name is blank", async () => {
    render(<NewProjectDialog />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Criar projeto" }));

    expect(await screen.findByText("Informe um nome para o projeto.")).toBeInTheDocument();
    expect(projectsApi.create).not.toHaveBeenCalled();
  });
});
