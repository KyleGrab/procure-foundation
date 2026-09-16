import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ProcurementLensDemoCallout } from "./ProcurementLensDemoCallout";

describe("ProcurementLensDemoCallout", () => {
  it("renders a working link to the Procurement Command Centre in local development", () => {
    render(<ProcurementLensDemoCallout nodeEnv="development" demoModeFlag={undefined} />);
    expect(screen.getByRole("link", { name: "Open Procurement Command Centre" })).toHaveAttribute(
      "href",
      "/dashboard/procurement"
    );
  });

  it("also renders when NEXT_PUBLIC_DEMO_MODE is explicitly 'true'", () => {
    render(<ProcurementLensDemoCallout nodeEnv="production" demoModeFlag="true" />);
    expect(screen.getByRole("link", { name: "Open Procurement Command Centre" })).toBeInTheDocument();
  });

  it("renders nothing in a production build with no demo-mode flag - the default deployment case", () => {
    render(<ProcurementLensDemoCallout nodeEnv="production" demoModeFlag={undefined} />);
    expect(screen.queryByRole("link", { name: "Open Procurement Command Centre" })).not.toBeInTheDocument();
  });
});
