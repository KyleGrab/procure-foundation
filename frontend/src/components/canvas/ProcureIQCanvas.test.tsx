/**
 * Confirms the illustrative-demo callout (PROCUREIQ-PRICE-REVIEW-DEMO-UX-R3) is wired into the
 * real Procurement lens correctly: only that lens, only in demo mode, and it never depends on
 * canvasApi resolving (mocked here to an empty graph - the "No data yet" state - so this stays
 * about the callout, not a re-test of the canvas's own data rendering).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ProcureIQCanvas } from "./ProcureIQCanvas";
import { canvasApi } from "@/lib/canvas-api";

let mockLensParam: string | null = null;

vi.mock("@/lib/canvas-api", () => ({
  canvasApi: { getNodes: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mockLensParam ? `lens=${mockLensParam}` : ""),
}));

beforeEach(() => {
  vi.mocked(canvasApi.getNodes).mockResolvedValue({ nodes: [], edges: [] });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("ProcureIQCanvas - illustrative demo callout", () => {
  it("shows a working link to the illustrative price review on the Procurement lens in demo mode", async () => {
    vi.stubEnv("NODE_ENV", "development");
    mockLensParam = "procurement";
    render(<ProcureIQCanvas />);
    expect(await screen.findByRole("link", { name: "Open illustrative price review" })).toHaveAttribute(
      "href",
      "/price-reviews/demo"
    );
  });

  it("does not show the callout on the Management Accounting lens", async () => {
    vi.stubEnv("NODE_ENV", "development");
    mockLensParam = "management";
    render(<ProcureIQCanvas />);
    await screen.findByText("No data yet for this lens.");
    expect(screen.queryByRole("link", { name: "Open illustrative price review" })).not.toBeInTheDocument();
  });

  it("does not show the callout on the Operations lens", async () => {
    vi.stubEnv("NODE_ENV", "development");
    mockLensParam = "operations";
    render(<ProcureIQCanvas />);
    await screen.findByText("No data yet for this lens.");
    expect(screen.queryByRole("link", { name: "Open illustrative price review" })).not.toBeInTheDocument();
  });

  it("does not show the callout in a production build with no demo-mode flag", async () => {
    vi.stubEnv("NODE_ENV", "production");
    mockLensParam = "procurement";
    render(<ProcureIQCanvas />);
    await screen.findByText("No data yet for this lens.");
    expect(screen.queryByRole("link", { name: "Open illustrative price review" })).not.toBeInTheDocument();
  });
});
