/**
 * Covers PROCUREIQ-PROCUREMENT-COMMAND-CENTRE-R1's core promise: every illustrative-only piece
 * disappears outside demo mode (so nothing here is ever a dead link to a route that 404s without
 * the flag), while the real, always-working parts (heading, Price Reviews/Contracts/Opportunities
 * cards, the secondary CTA) are present either way.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import ProcurementCommandCentrePage from "./page";
import { DEMO_REVIEW } from "@/lib/price-review-demo-data";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("ProcurementCommandCentrePage - demo mode on", () => {
  it("shows the illustrative banner, primary CTA, work queue, and Supplier Changes card", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    render(<ProcurementCommandCentrePage />);

    expect(
      screen.getByText("Illustrative demo data — not live supplier or customer data.")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open illustrative price review/ })).toHaveAttribute(
      "href",
      "/price-reviews/demo"
    );
    expect(screen.getByRole("heading", { name: "What needs attention" })).toBeInTheDocument();
    // Appears in both the queue item and the Supplier Changes card - both reuse the same
    // illustrative dataset rather than each inventing its own supplier name.
    expect(screen.getAllByText(new RegExp(DEMO_REVIEW.supplier_name)).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Open illustrative walkthrough/ })).toHaveAttribute(
      "href",
      "/price-reviews/demo"
    );
  });

  it("the work-queue counts match what the demo dataset's own classification actually produces - not hardcoded separately from it", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    render(<ProcurementCommandCentrePage />);
    // DEMO_LINES has exactly 3 needs_attention lines and 1 unknown line - see
    // price-review-line-classification.test.ts for the classification rules themselves.
    expect(screen.getByText(/3 lines need attention/)).toBeInTheDocument();
    expect(screen.getByText(/1 line has no confirmed match/)).toBeInTheDocument();
  });
});

describe("ProcurementCommandCentrePage - demo mode off (production, no flag)", () => {
  it("hides every illustrative-only element - never a dead link to a 404ing demo route", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "");
    render(<ProcurementCommandCentrePage />);

    expect(
      screen.queryByText("Illustrative demo data — not live supplier or customer data.")
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open illustrative price review/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What needs attention" })).not.toBeInTheDocument();
    expect(screen.queryByText("Supplier Changes")).not.toBeInTheDocument();
  });

  it("still shows the real heading and always-working secondary CTA", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "");
    render(<ProcurementCommandCentrePage />);
    expect(screen.getByRole("heading", { name: "Procurement" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View Price Reviews history/ })).toHaveAttribute(
      "href",
      "/price-reviews"
    );
  });
});

describe("ProcurementCommandCentrePage - Contracts and Opportunities, always", () => {
  for (const nodeEnv of ["development", "production"]) {
    it(`states the honest unavailable reason and still navigates somewhere real (NODE_ENV=${nodeEnv})`, () => {
      vi.stubEnv("NODE_ENV", nodeEnv);
      vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "");
      render(<ProcurementCommandCentrePage />);

      expect(screen.getByText("Not connected — requires live contract data.")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Open Contracts workspace/ })).toHaveAttribute(
        "href",
        "/dashboard/contracts"
      );

      expect(screen.getByText("Not connected — requires live spend data.")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Open Opportunities workspace/ })).toHaveAttribute(
        "href",
        "/dashboard/opportunities"
      );
    });
  }

  it("the real Price Reviews card never claims a count the app can't back up", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "");
    render(<ProcurementCommandCentrePage />);
    const priceReviewsLinks = screen.getAllByRole("link", { name: /Price Reviews/ });
    expect(priceReviewsLinks.length).toBeGreaterThan(0);
    // No digit anywhere near the card's own text - this page never fabricates a review count.
    expect(screen.queryByText(/\d+ price reviews?/i)).not.toBeInTheDocument();
  });
});
