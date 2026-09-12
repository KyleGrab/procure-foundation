/**
 * Component tests for AuditActivityTable's consolidation-flag review wiring
 * (CONSOLIDATION-REVIEW-UI-R1). WRITTEN, NOT EXECUTED - same category as
 * src/components/treasury/FxExposureCard.test.tsx: rendering JSX and querying a DOM needs
 * @testing-library/react + jsdom, neither of which could be installed (`npm install` is actively
 * blocked in this sandbox - 403 Forbidden by security policy, confirmed directly, not assumed).
 *
 * Mocks @/lib/dashboard-api's opportunitiesApi entirely (no real fetch involved) - "mocked API
 * calls" per this phase's own instructions - so these tests exercise only this component's own
 * request-building, refetch-after-success, and error-presentation logic.
 *
 * This file exists to run correctly the moment real test infrastructure is set up
 * (`npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom` + a
 * vitest.config.ts with environment: "jsdom"), not as a substitute for that setup.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AuditActivityTable } from "./AuditActivityTable";
import { opportunitiesApi } from "@/lib/dashboard-api";

vi.mock("@/lib/dashboard-api", () => ({
  opportunitiesApi: {
    duplicateSkuFlags: vi.fn(),
    consolidationFlags: vi.fn(),
    reviewDuplicateSkuFlag: vi.fn(),
    reviewConsolidationFlag: vi.fn(),
  },
}));

const FLAG_PUBLIC_ID = "8b1e7f4a-8f0e-4a3f-9d2b-2b9f6b8e6c11"; // deliberately not a small int -
// proves the component sends the flag's real public identifier, never an internal row id.

const FLAGGED_CONSOLIDATION_ROW = {
  public_id: FLAG_PUBLIC_ID,
  description_a: "Frozen Chicken Portions 2kg",
  description_b: "Frozen Chicken Portions 2kg (Alt Supplier)",
  similarity_score: "0.9200",
  status: "flagged",
};

function mockEmptyDuplicates() {
  vi.mocked(opportunitiesApi.duplicateSkuFlags).mockResolvedValue([]);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AuditActivityTable - consolidation flag review", () => {
  it("sends no review request before any user action", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags).mockResolvedValue([FLAGGED_CONSOLIDATION_ROW]);
    render(<AuditActivityTable />);
    await screen.findByText("Recommend consolidation");
    expect(opportunitiesApi.reviewConsolidationFlag).not.toHaveBeenCalled();
  });

  it("Mark under review sends the exact expected request using the flag's public ID", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags).mockResolvedValue([FLAGGED_CONSOLIDATION_ROW]);
    vi.mocked(opportunitiesApi.reviewConsolidationFlag).mockResolvedValue({
      public_id: FLAG_PUBLIC_ID, status: "under_review", review_notes: null, reviewed_at: "2026-09-13T00:00:00Z",
    });
    render(<AuditActivityTable />);
    fireEvent.click(await screen.findByText("Mark under review"));
    await waitFor(() => expect(opportunitiesApi.reviewConsolidationFlag).toHaveBeenCalledTimes(1));
    expect(opportunitiesApi.reviewConsolidationFlag).toHaveBeenCalledWith(FLAG_PUBLIC_ID, "mark_under_review");
  });

  it("Recommend consolidation sends the exact expected request", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags).mockResolvedValue([FLAGGED_CONSOLIDATION_ROW]);
    vi.mocked(opportunitiesApi.reviewConsolidationFlag).mockResolvedValue({
      public_id: FLAG_PUBLIC_ID, status: "consolidation_recommended", review_notes: null, reviewed_at: "2026-09-13T00:00:00Z",
    });
    render(<AuditActivityTable />);
    fireEvent.click(await screen.findByText("Recommend consolidation"));
    await waitFor(() => expect(opportunitiesApi.reviewConsolidationFlag).toHaveBeenCalledTimes(1));
    expect(opportunitiesApi.reviewConsolidationFlag).toHaveBeenCalledWith(FLAG_PUBLIC_ID, "recommend_consolidation");
  });

  it("Reject sends the exact expected request", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags).mockResolvedValue([FLAGGED_CONSOLIDATION_ROW]);
    vi.mocked(opportunitiesApi.reviewConsolidationFlag).mockResolvedValue({
      public_id: FLAG_PUBLIC_ID, status: "rejected", review_notes: null, reviewed_at: "2026-09-13T00:00:00Z",
    });
    render(<AuditActivityTable />);
    fireEvent.click(await screen.findByText("Reject"));
    await waitFor(() => expect(opportunitiesApi.reviewConsolidationFlag).toHaveBeenCalledTimes(1));
    expect(opportunitiesApi.reviewConsolidationFlag).toHaveBeenCalledWith(FLAG_PUBLIC_ID, "reject");
  });

  it("refetches and reflects the backend's own state after a successful review - never a guessed client-side transition", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags)
      .mockResolvedValueOnce([FLAGGED_CONSOLIDATION_ROW])
      .mockResolvedValueOnce([{ ...FLAGGED_CONSOLIDATION_ROW, status: "under_review" }]);
    vi.mocked(opportunitiesApi.reviewConsolidationFlag).mockResolvedValue({
      public_id: FLAG_PUBLIC_ID, status: "under_review", review_notes: null, reviewed_at: "2026-09-13T00:00:00Z",
    });
    render(<AuditActivityTable />);
    fireEvent.click(await screen.findByText("Mark under review"));
    // A second fetch of the list happened (the refetch), and the row's badge now reflects it -
    // the component never wrote "under_review" into local state by itself.
    await waitFor(() => expect(opportunitiesApi.consolidationFlags).toHaveBeenCalledTimes(2));
    await screen.findByText("under review");
  });

  it("presents a 409 invalid-transition failure safely, never a raw stack trace", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags).mockResolvedValue([FLAGGED_CONSOLIDATION_ROW]);
    vi.mocked(opportunitiesApi.reviewConsolidationFlag).mockRejectedValue(
      new Error("Cannot go from 'flagged' to 'consolidation_recommended' via action 'recommend_consolidation'")
    );
    render(<AuditActivityTable />);
    fireEvent.click(await screen.findByText("Recommend consolidation"));
    const message = await screen.findByText(/Cannot go from/);
    expect(message.textContent).not.toMatch(/Traceback|at Object\.|node_modules/);
  });

  it("presents a 403 permission failure safely", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags).mockResolvedValue([FLAGGED_CONSOLIDATION_ROW]);
    vi.mocked(opportunitiesApi.reviewConsolidationFlag).mockRejectedValue(
      new Error("Role 'viewer' does not have permission 'edit_suppliers' for this action")
    );
    render(<AuditActivityTable />);
    fireEvent.click(await screen.findByText("Reject"));
    await screen.findByText(/does not have permission/);
  });

  it("presents a generic/unexpected failure with a safe fallback message", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags).mockResolvedValue([FLAGGED_CONSOLIDATION_ROW]);
    vi.mocked(opportunitiesApi.reviewConsolidationFlag).mockRejectedValue("not even an Error instance");
    render(<AuditActivityTable />);
    fireEvent.click(await screen.findByText("Mark under review"));
    await screen.findByText("Could not record the review decision");
  });

  it("every consolidation action states plainly that this is a review decision only", async () => {
    mockEmptyDuplicates();
    vi.mocked(opportunitiesApi.consolidationFlags).mockResolvedValue([FLAGGED_CONSOLIDATION_ROW]);
    render(<AuditActivityTable />);
    for (const label of ["Mark under review", "Recommend consolidation", "Reject"]) {
      const button = await screen.findByText(label);
      const title = button.getAttribute("title") ?? "";
      expect(title).toMatch(/review decision only/i);
      // States plainly what it does NOT do - "does not merge suppliers, reassign anything, or
      // write a financial fact" - never an affirmative claim that any of those will happen.
      expect(title).toMatch(/does not merge suppliers/i);
      expect(title.toLowerCase()).not.toMatch(
        /will merge|will reassign|automatically merge|creates? an opportunity|changes? the price/
      );
    }
  });
});
