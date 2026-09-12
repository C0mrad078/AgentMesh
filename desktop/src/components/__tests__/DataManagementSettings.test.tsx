import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  databaseApi: {
    createBackup: vi.fn(),
    listBackups: vi.fn(),
    restoreBackup: vi.fn(),
    integrityCheck: vi.fn(),
  },
  learningApi: {
    export: vi.fn(),
  },
}));

import { databaseApi } from "@/services/api";
import { DataManagementSettings } from "@/components/DataManagementSettings";

describe("DataManagementSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(databaseApi.listBackups).mockResolvedValue([]);
  });

  it("shows an empty state before any backup exists", async () => {
    render(<DataManagementSettings />);
    expect(await screen.findByText("Nenhum backup ainda.")).toBeInTheDocument();
  });

  it("creates a backup and refreshes the list", async () => {
    vi.mocked(databaseApi.createBackup).mockResolvedValue({
      path: "/data/backups/2026-01-01.db", created_at: "2026-01-01", size_bytes: 2048,
    });
    render(<DataManagementSettings />);
    await screen.findByText("Nenhum backup ainda.");

    vi.mocked(databaseApi.listBackups).mockResolvedValue([
      { path: "/data/backups/2026-01-01.db", created_at: "2026-01-01", size_bytes: 2048 },
    ]);
    await userEvent.click(screen.getByRole("button", { name: "Fazer backup agora" }));

    await waitFor(() => expect(databaseApi.createBackup).toHaveBeenCalled());
    expect(await screen.findByText("2026-01-01")).toBeInTheDocument();
  });

  it("requires a second confirmation click before restoring", async () => {
    vi.mocked(databaseApi.listBackups).mockResolvedValue([
      { path: "/data/backups/2026-01-01.db", created_at: "2026-01-01", size_bytes: 2048 },
    ]);
    vi.mocked(databaseApi.restoreBackup).mockResolvedValue({
      restored_from: "/data/backups/2026-01-01.db", restart_recommended: true,
    });
    render(<DataManagementSettings />);
    await screen.findByText("2026-01-01");

    await userEvent.click(screen.getByRole("button", { name: "Restaurar" }));
    expect(databaseApi.restoreBackup).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Confirmar restauração" }));
    await waitFor(() =>
      expect(databaseApi.restoreBackup).toHaveBeenCalledWith("/data/backups/2026-01-01.db"),
    );
  });

  it("runs an integrity check and shows the result", async () => {
    vi.mocked(databaseApi.integrityCheck).mockResolvedValue({ ok: true, issues: [] });
    render(<DataManagementSettings />);
    await userEvent.click(screen.getByRole("button", { name: "Verificar integridade" }));
    expect(await screen.findByText("Banco de dados íntegro.")).toBeInTheDocument();
  });
});
