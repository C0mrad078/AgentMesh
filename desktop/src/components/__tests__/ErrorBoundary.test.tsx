import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function Bomb({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("boom");
  }
  return <div>All good</div>;
}

describe("ErrorBoundary", () => {
  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary boundaryName="Test">
        <Bomb shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("All good")).toBeInTheDocument();
  });

  it("catches a render error and shows a fallback naming the boundary", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary boundaryName="Workspace">
        <Bomb shouldThrow />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("error-boundary")).toBeInTheDocument();
    expect(screen.getByText(/Workspace/)).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("lets the user retry, remounting children", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    let shouldThrow = true;
    function Toggle() {
      return <Bomb shouldThrow={shouldThrow} />;
    }
    render(
      <ErrorBoundary boundaryName="Workspace">
        <Toggle />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("error-boundary")).toBeInTheDocument();

    shouldThrow = false;
    await userEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(screen.getByText("All good")).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
