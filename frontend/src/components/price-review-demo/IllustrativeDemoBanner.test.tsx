import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { IllustrativeDemoBanner } from "./IllustrativeDemoBanner";

describe("IllustrativeDemoBanner", () => {
  it("states plainly that the data is illustrative, not live", () => {
    render(<IllustrativeDemoBanner />);
    expect(
      screen.getByText("Illustrative demo data — not live supplier or customer data.")
    ).toBeInTheDocument();
  });

  it("is announced to assistive tech without requiring focus", () => {
    render(<IllustrativeDemoBanner />);
    expect(screen.getByRole("status")).toHaveTextContent("Illustrative demo data");
  });
});
