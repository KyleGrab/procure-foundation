/**
 * Covers the entry link's non-production gating. isDemoModeEnabled itself is exhaustively unit
 * tested in lib/demo-mode.test.ts; this file checks that the component actually wires it up -
 * env combinations passed as props here, rather than mutating global process.env, so this stays
 * deterministic regardless of test execution order.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DemoWalkthroughEntry } from "./DemoWalkthroughEntry";

describe("DemoWalkthroughEntry", () => {
  it("renders the entry link in local development", () => {
    render(<DemoWalkthroughEntry nodeEnv="development" demoModeFlag={undefined} />);
    expect(screen.getByRole("link", { name: "Open illustrative walkthrough" })).toBeInTheDocument();
  });

  it("renders the entry link when NEXT_PUBLIC_DEMO_MODE is explicitly 'true'", () => {
    render(<DemoWalkthroughEntry nodeEnv="production" demoModeFlag="true" />);
    expect(screen.getByRole("link", { name: "Open illustrative walkthrough" })).toBeInTheDocument();
  });

  it("never renders in a production build with no demo-mode flag set - the default deployment case", () => {
    render(<DemoWalkthroughEntry nodeEnv="production" demoModeFlag={undefined} />);
    expect(screen.queryByRole("link", { name: "Open illustrative walkthrough" })).not.toBeInTheDocument();
  });

  it("does not render for a near-miss flag value such as 'True'", () => {
    render(<DemoWalkthroughEntry nodeEnv="production" demoModeFlag="True" />);
    expect(screen.queryByRole("link", { name: "Open illustrative walkthrough" })).not.toBeInTheDocument();
  });

  it("the rendered link points at the demo route", () => {
    render(<DemoWalkthroughEntry nodeEnv="development" demoModeFlag={undefined} />);
    expect(screen.getByRole("link", { name: "Open illustrative walkthrough" })).toHaveAttribute(
      "href",
      "/price-reviews/demo"
    );
  });
});
