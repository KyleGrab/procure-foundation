/**
 * Pure FX display-state and formatting logic - deliberately zero imports (no apiFetch, no
 * authHeaders, no network dependency of any kind). This separation exists for a real reason
 * beyond testability: it mirrors this codebase's own backend philosophy (§2.1 - pure logic
 * always separated from DB/framework code) applied to the frontend for the first time this
 * engagement. treasury-api.ts (the actual network client) imports its types from here rather
 * than the reverse.
 *
 * Because this file has no dependencies at all, it can be executed directly and genuinely via
 * `node --test src/lib/treasury-display.test.ts` (Node 22's native TypeScript support) - not
 * "written but not executed" the way every React component test in this engagement has to be
 * (no npm install possible: confirmed blocked, 403 Forbidden, checked directly before writing
 * this comment, not assumed).
 */

export interface FxExposureResult {
  isHedged: boolean;
  unrealizedVariance: number | null;
  hedgingGainLoss: number | null;
  fecContractRate: number | null;
}

export interface FxDisplayState {
  mode: "hedged" | "unhedged";
  label: string;
  value: number;
  isAdverse: boolean;
}

/**
 * Re-checks mutual exclusivity at the frontend boundary - defense in depth, mirroring the
 * backend's own CHECK constraint (fx_transaction_snapshots) and pure-function branch
 * (calculate_fx_transaction_exposure). Never trusts an upstream payload blindly even though the
 * backend is already known-correct: a future backend change, a hand-crafted request bypassing
 * the real route, or a network-layer corruption should fail loudly here with a thrown error, not
 * silently render two conflicting numbers - or the wrong one - in a dashboard summary.
 */
export function resolveFxDisplayState(exposure: FxExposureResult): FxDisplayState {
  if (exposure.isHedged) {
    if (exposure.unrealizedVariance !== null) {
      throw new Error("FX display integrity violation: isHedged=true but unrealizedVariance is not null");
    }
    if (exposure.hedgingGainLoss === null) {
      throw new Error("FX display integrity violation: isHedged=true but hedgingGainLoss is null");
    }
    return {
      mode: "hedged", label: "Hedging Gain/Loss (FEC-locked)",
      value: exposure.hedgingGainLoss, isAdverse: exposure.hedgingGainLoss < 0,
    };
  }
  if (exposure.hedgingGainLoss !== null) {
    throw new Error("FX display integrity violation: isHedged=false but hedgingGainLoss is not null");
  }
  if (exposure.unrealizedVariance === null) {
    throw new Error("FX display integrity violation: isHedged=false but unrealizedVariance is null");
  }
  return {
    mode: "unhedged", label: "Unrealized Variance (spot exposure)",
    value: exposure.unrealizedVariance, isAdverse: exposure.unrealizedVariance > 0,
  };
}

/**
 * Cent-level precision, deliberately NOT reusing dashboard-api.ts's formatZAR - that formatter
 * uses maximumFractionDigits: 0 (whole Rand only), which would silently truncate exactly the
 * cent-level precision this domain's own forensic tests require (backend
 * tests_pure/test_treasury_engine.py's late-rounding precision test, verified to the cent).
 */
export function formatZARPrecise(amount: number): string {
  return new Intl.NumberFormat("en-ZA", {
    style: "currency", currency: "ZAR", minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(amount);
}
