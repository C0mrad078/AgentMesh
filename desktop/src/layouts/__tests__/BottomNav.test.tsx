import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { BottomNav } from "@/layouts/BottomNav";
import { useUiStore } from "@/stores/uiStore";

describe("BottomNav", () => {
  it("replaces the old fixed sidebar with a thin nav strip listing every V2 destination", () => {
    render(<BottomNav />);
    for (const page of ["office", "projects", "team", "workspace", "executions", "memory", "providers", "learning", "settings"]) {
      expect(screen.getByTestId(`nav-${page}`)).toBeInTheDocument();
    }
  });

  it("clicking a destination switches the active page", async () => {
    useUiStore.setState({ activePage: "office" });
    render(<BottomNav />);

    await userEvent.click(screen.getByTestId("nav-team"));

    expect(useUiStore.getState().activePage).toBe("team");
  });

  it("highlights the currently active destination", () => {
    useUiStore.setState({ activePage: "projects" });
    render(<BottomNav />);
    expect(screen.getByTestId("nav-projects").className).toContain("text-accent-foreground");
    expect(screen.getByTestId("nav-office").className).not.toContain("text-accent-foreground");
  });
});
