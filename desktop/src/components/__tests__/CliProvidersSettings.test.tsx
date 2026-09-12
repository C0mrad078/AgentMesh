import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  providerCliApi: {
    listStatuses: vi.fn(),
  },
}));

import { providerCliApi } from "@/services/api";
import { CliProvidersSettings } from "@/components/CliProvidersSettings";
import type { CliProviderName, CliProviderStatus } from "@/types";

function makeStatuses(
  overrides: Partial<Record<CliProviderName, Partial<CliProviderStatus>>> = {},
): Record<CliProviderName, CliProviderStatus> {
  const base: CliProviderStatus = {
    access_method: "cli",
    state: "not_installed",
    version: null,
    auth_method: null,
    model: null,
    detail: null,
  };
  return {
    codex_cli: { ...base, ...overrides.codex_cli },
    claude_code_cli: { ...base, ...overrides.claude_code_cli },
    gemini_cli: { ...base, ...overrides.gemini_cli },
  };
}

describe("CliProvidersSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows all three providers with their real status", async () => {
    vi.mocked(providerCliApi.listStatuses).mockResolvedValue(
      makeStatuses({
        codex_cli: { state: "connected", version: "codex-cli 0.154.0", auth_method: "ChatGPT" },
      }),
    );

    render(<CliProvidersSettings />);

    expect(await screen.findByText("Codex CLI")).toBeInTheDocument();
    expect(screen.getByText("Claude Code CLI")).toBeInTheDocument();
    expect(screen.getByText("Gemini CLI")).toBeInTheDocument();
    expect(screen.getByText("Conectado")).toBeInTheDocument();
    expect(screen.getByText(/Método: ChatGPT/)).toBeInTheDocument();
    expect(screen.getAllByText("Não instalado")).toHaveLength(2);
  });

  it("shows install instructions for a not-installed provider", async () => {
    vi.mocked(providerCliApi.listStatuses).mockResolvedValue(makeStatuses());

    render(<CliProvidersSettings />);

    await screen.findByText("Codex CLI");
    expect(screen.getByText("npm install -g @openai/codex")).toBeInTheDocument();
  });

  it("re-queries status when Verificar novamente is clicked", async () => {
    vi.mocked(providerCliApi.listStatuses)
      .mockResolvedValueOnce(makeStatuses())
      .mockResolvedValueOnce(makeStatuses({ codex_cli: { state: "connected" } }));

    render(<CliProvidersSettings />);
    await screen.findByText("Codex CLI");

    const user = userEvent.setup();
    await user.click(screen.getAllByRole("button", { name: /Verificar novamente/ })[0]);

    await waitFor(() => expect(providerCliApi.listStatuses).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Conectado")).toBeInTheDocument();
  });

  it("shows an error message if the status query fails", async () => {
    vi.mocked(providerCliApi.listStatuses).mockRejectedValue(new Error("bridge unavailable"));

    render(<CliProvidersSettings />);

    expect(await screen.findByText("bridge unavailable")).toBeInTheDocument();
  });
});
