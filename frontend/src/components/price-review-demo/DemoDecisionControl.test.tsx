/**
 * Confirms the demo decision interaction is genuinely local-only: clicking a decision button
 * never triggers a network request, only updates whatever local state the caller wires up, and
 * the "Demo-only — not saved to ProcureIQ." caption is present before and after a choice is made.
 */
import { useState } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DemoDecisionControl, type DemoDecision } from "./DemoDecisionControl";

function StatefulHarness() {
  const [decision, setDecision] = useState<DemoDecision | null>(null);
  return <DemoDecisionControl lineId="demo-line-01" decision={decision} onDecide={(_id, d) => setDecision(d)} />;
}

describe("DemoDecisionControl", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("shows the demo-only disclosure before any decision is made", () => {
    render(<DemoDecisionControl lineId="demo-line-01" decision={null} onDecide={() => {}} />);
    expect(screen.getByText(/Demo-only — not saved to ProcureIQ\./)).toBeInTheDocument();
  });

  it("records the decision locally and reflects it in the UI, without calling fetch", () => {
    render(<StatefulHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(screen.getByText(/Recorded locally as "Accept\."/)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("calls onDecide with the exact line id and chosen decision", () => {
    const onDecide = vi.fn();
    render(<DemoDecisionControl lineId="demo-line-02" decision={null} onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: "Negotiate" }));
    expect(onDecide).toHaveBeenCalledWith("demo-line-02", "negotiate");
  });

  it("marks the chosen button as pressed via aria-pressed", () => {
    render(<StatefulHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Investigate" }));
    expect(screen.getByRole("button", { name: "Investigate" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Accept" })).toHaveAttribute("aria-pressed", "false");
  });
});
