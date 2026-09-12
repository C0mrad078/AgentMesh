import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", () => ({
  budgetApi: {
    get: vi.fn(),
    set: vi.fn(),
  },
}));

import { budgetApi } from "@/services/api";
import { BudgetSettings } from "@/components/BudgetSettings";

describe("BudgetSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads existing limits into the inputs", async () => {
    vi.mocked(budgetApi.get).mockResolvedValue({
      max_per_execution_usd: 2,
      daily_limit_usd: 10,
      monthly_limit_usd: null,
      soft_limit_ratio: 0.8,
    });

    render(<BudgetSettings />);

    expect(await screen.findByLabelText("Máximo por execução (USD)")).toHaveValue(2);
    expect(screen.getByLabelText("Limite diário (USD)")).toHaveValue(10);
    expect(screen.getByLabelText("Limite mensal (USD)")).toHaveValue(null);
  });

  it("saves edited limits, treating a blank field as no limit", async () => {
    vi.mocked(budgetApi.get).mockResolvedValue({
      max_per_execution_usd: null,
      daily_limit_usd: null,
      monthly_limit_usd: null,
      soft_limit_ratio: 0.8,
    });
    vi.mocked(budgetApi.set).mockResolvedValue({
      max_per_execution_usd: 5,
      daily_limit_usd: null,
      monthly_limit_usd: null,
      soft_limit_ratio: 0.8,
    });

    render(<BudgetSettings />);
    await screen.findByLabelText("Máximo por execução (USD)");

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Máximo por execução (USD)"), "5");
    await user.click(screen.getByRole("button", { name: "Salvar limites" }));

    await waitFor(() =>
      expect(budgetApi.set).toHaveBeenCalledWith({
        max_per_execution_usd: 5,
        daily_limit_usd: null,
        monthly_limit_usd: null,
      }),
    );
    expect(await screen.findByText("Salvo.")).toBeInTheDocument();
  });
});
