/**
 * Component tests for FxExposureCard. WRITTEN, NOT EXECUTED - this is not the same category as
 * treasury-display.test.ts (which genuinely ran, 9/9 passing, via Node's native TS execution).
 * Rendering JSX and querying a DOM needs @testing-library/react + jsdom, neither of which could
 * be installed: `npm install` is actively blocked in this sandbox (403 Forbidden by security
 * policy - confirmed directly with a real install attempt before writing this file, not assumed
 * or inferred from "no npm install has ever been run").
 *
 * This file exists to run correctly the moment real test infrastructure is set up
 * (`npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom` + a
 * vitest.config.ts with environment: "jsdom"), not as a substitute for that setup.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { FxExposureCard } from "./FxExposureCard";
import type { FxExposureResult } from "@/lib/treasury-display";

describe("FxExposureCard", () => {
  it("renders the unhedged unrealized variance, not the hedging gain/loss label", () => {
    const exposure: FxExposureResult = {
      isHedged: false, unrealizedVariance: 180000.0, hedgingGainLoss: null, fecContractRate: null,
    };
    render(<FxExposureCard exposure={exposure} currencyCode="USD" />);
    expect(screen.getByText("Unrealized Variance (spot exposure)")).toBeInTheDocument();
    expect(screen.queryByText(/Hedging Gain\/Loss/)).not.toBeInTheDocument();
    expect(screen.getByText(/R\s?180\s?000,00/)).toBeInTheDocument();
  });

  it("renders the hedged gain, not the unrealized variance label, and shows the FEC rate", () => {
    const exposure: FxExposureResult = {
      isHedged: true, unrealizedVariance: null, hedgingGainLoss: 160000.0, fecContractRate: 18.2,
    };
    render(<FxExposureCard exposure={exposure} currencyCode="USD" />);
    expect(screen.getByText("Hedging Gain/Loss (FEC-locked)")).toBeInTheDocument();
    expect(screen.queryByText(/Unrealized Variance/)).not.toBeInTheDocument();
    expect(screen.getByText(/FEC locked at 18.2000/)).toBeInTheDocument();
  });

  it("renders a visible diagnostic state, not a crash, when the payload violates mutual exclusivity", () => {
    const malformed = {
      isHedged: true, unrealizedVariance: 999999, hedgingGainLoss: 160000.0, fecContractRate: 18.2,
    } as FxExposureResult;
    render(<FxExposureCard exposure={malformed} currencyCode="USD" />);
    expect(screen.getByText("FX Exposure — Diagnostic State")).toBeInTheDocument();
  });

  it("applies the adverse (rose) color for a positive unrealized variance", () => {
    const exposure: FxExposureResult = {
      isHedged: false, unrealizedVariance: 180000.0, hedgingGainLoss: null, fecContractRate: null,
    };
    render(<FxExposureCard exposure={exposure} currencyCode="USD" />);
    const value = screen.getByText(/R\s?180\s?000,00/);
    expect(value.className).toContain("text-rose-400");
  });

  it("applies the favourable (emerald) color for a negative (favourable) hedging gain", () => {
    const exposure: FxExposureResult = {
      isHedged: true, unrealizedVariance: null, hedgingGainLoss: 160000.0, fecContractRate: 18.2,
    };
    render(<FxExposureCard exposure={exposure} currencyCode="USD" />);
    const value = screen.getByText(/R\s?160\s?000,00/);
    expect(value.className).toContain("text-emerald-400");
  });
});
