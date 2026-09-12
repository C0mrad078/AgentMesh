import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  providersApi: {
    list: vi.fn(),
    setCredential: vi.fn(),
    removeCredential: vi.fn(),
    testConnection: vi.fn(),
  },
}));

import { providersApi } from "@/services/api";
import { ProvidersSettings } from "@/components/ProvidersSettings";
import type { ProviderInfo } from "@/types";

function makeProvider(overrides: Partial<ProviderInfo> = {}): ProviderInfo {
  return {
    provider: "anthropic",
    display_name: "Claude (Anthropic)",
    enabled: false,
    connected: false,
    health: "unknown",
    ...overrides,
  };
}

describe("ProvidersSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a not-configured provider and disables save until a key is typed", async () => {
    vi.mocked(providersApi.list).mockResolvedValue([makeProvider()]);
    render(<ProvidersSettings />);

    expect(await screen.findByText("Claude (Anthropic)")).toBeInTheDocument();
    expect(screen.getByText("Não configurado")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar" })).toBeDisabled();
  });

  it("saves a typed API key and reloads the provider list", async () => {
    vi.mocked(providersApi.list)
      .mockResolvedValueOnce([makeProvider()])
      .mockResolvedValueOnce([makeProvider({ connected: true, enabled: true, health: "online" })]);
    vi.mocked(providersApi.setCredential).mockResolvedValue({ provider: "anthropic", enabled: true });

    render(<ProvidersSettings />);
    await screen.findByText("Claude (Anthropic)");

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("API Key"), "sk-test-key");
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() =>
      expect(providersApi.setCredential).toHaveBeenCalledWith("anthropic", "sk-test-key"),
    );
    expect(await screen.findByText(/Conectado · Online/)).toBeInTheDocument();
    expect(screen.getByLabelText("API Key")).toHaveValue("");
  });

  it("runs a connection test and shows the result without saving the key", async () => {
    vi.mocked(providersApi.list).mockResolvedValue([makeProvider()]);
    vi.mocked(providersApi.testConnection).mockResolvedValue({
      provider: "anthropic",
      result: "invalid_key",
    });

    render(<ProvidersSettings />);
    await screen.findByText("Claude (Anthropic)");

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("API Key"), "sk-bad-key");
    await user.click(screen.getByRole("button", { name: "Testar conexão" }));

    expect(await screen.findByText("Chave inválida")).toBeInTheDocument();
    expect(providersApi.setCredential).not.toHaveBeenCalled();
  });

  it("removes a saved credential", async () => {
    vi.mocked(providersApi.list)
      .mockResolvedValueOnce([makeProvider({ connected: true, enabled: true, health: "online" })])
      .mockResolvedValueOnce([makeProvider()]);
    vi.mocked(providersApi.removeCredential).mockResolvedValue({ provider: "anthropic", enabled: false });

    render(<ProvidersSettings />);
    await screen.findByText(/Conectado · Online/);

    await userEvent.click(screen.getByRole("button", { name: "Remover" }));

    await waitFor(() => expect(providersApi.removeCredential).toHaveBeenCalledWith("anthropic"));
    expect(await screen.findByText("Não configurado")).toBeInTheDocument();
  });
});
