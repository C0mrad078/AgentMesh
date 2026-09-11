import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StepBoard } from "@/components/StepBoard";

describe("StepBoard", () => {
  it("renders all six pipeline phases even with no progress yet", () => {
    render(<StepBoard phases={[]} />);
    expect(screen.getByTestId("step-intent_analysis")).toBeInTheDocument();
    expect(screen.getByTestId("step-planning")).toBeInTheDocument();
    expect(screen.getByTestId("step-routing")).toBeInTheDocument();
    expect(screen.getByTestId("step-execution")).toBeInTheDocument();
    expect(screen.getByTestId("step-verification")).toBeInTheDocument();
    expect(screen.getByTestId("step-aggregation")).toBeInTheDocument();
  });

  it("reflects the status of a reported phase", () => {
    render(
      <StepBoard
        phases={[
          { phase: "intent_analysis", label: "Analisando intenção", status: "completed", detail: null },
          { phase: "planning", label: "Criando plano", status: "running", detail: null },
        ]}
      />,
    );
    expect(screen.getByTestId("step-intent_analysis")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-planning")).toHaveAttribute("data-status", "running");
    expect(screen.getByTestId("step-routing")).toHaveAttribute("data-status", "pending");
  });
});
