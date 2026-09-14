import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  memoryApi: { list: vi.fn() },
}));

import { memoryApi } from "@/services/api";
import { MemoryPage } from "@/pages/MemoryPage";
import { useProjectsStore } from "@/stores/projectsStore";
import type { MemoryRecordItem } from "@/types";

function record(overrides: Partial<MemoryRecordItem> = {}): MemoryRecordItem {
  return {
    id: "mem_1",
    project_id: "proj_1",
    kind: "fact",
    category: "stack",
    key: "stack.language",
    value: { language: "python" },
    importance: 0.7,
    confidence: 0.9,
    provenance: { source_execution_id: null, source_file: null, source_user_input: true },
    valid_from: "now",
    valid_until: null,
    superseded_by: null,
    created_at: "now",
    updated_at: "now",
    ...overrides,
  };
}

describe("MemoryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectsStore.setState({ projects: [], selectedProjectId: null, loaded: true, loading: false, error: null });
  });

  it("asks the user to pick a project when none is selected", () => {
    render(<MemoryPage />);
    expect(screen.getByText("Nenhum projeto selecionado")).toBeInTheDocument();
    expect(memoryApi.list).not.toHaveBeenCalled();
  });

  it("shows an honest empty state for a project with no memories yet", async () => {
    useProjectsStore.setState({
      projects: [{ id: "proj_1", name: "AgentMash", description: "", workspace_path: null, status: "active", config: {}, created_at: "now", updated_at: "now" }],
      selectedProjectId: "proj_1",
    });
    vi.mocked(memoryApi.list).mockResolvedValue([]);
    render(<MemoryPage />);
    expect(await screen.findByText("Nenhuma memória registrada ainda")).toBeInTheDocument();
  });

  it("lists real memory records for the selected project", async () => {
    useProjectsStore.setState({
      projects: [{ id: "proj_1", name: "AgentMash", description: "", workspace_path: null, status: "active", config: {}, created_at: "now", updated_at: "now" }],
      selectedProjectId: "proj_1",
    });
    vi.mocked(memoryApi.list).mockResolvedValue([record()]);
    render(<MemoryPage />);
    expect(await screen.findByText("stack.language")).toBeInTheDocument();
    expect(memoryApi.list).toHaveBeenCalledWith("proj_1");
  });
});
