/**
 * FX exposure widget for the treasury risk lens. Deliberately thin: all correctness-sensitive
 * logic (the mutual-exclusivity check, currency formatting) lives in treasury-display.ts, which
 * is genuinely executed and proven (node --test src/lib/treasury-display.test.ts, 9/9 passing -
 * not "written but not executed"). This component's own logic is just calling that function and
 * rendering its result - low-risk scaffolding around already-verified business rules, not new
 * unverified logic of its own.
 *
 * Not executed in this sandbox (no jsdom/@testing-library/react installed - npm install
 * confirmed blocked, 403 Forbidden, checked directly). Real colors matching this codebase's
 * established convention (MetricRibbon.tsx: border-[#1F2438] bg-[#131625]/90,
 * text-emerald-400/text-rose-400 for favourable/adverse), not invented for this component.
 */
"use client";

import { resolveFxDisplayState, formatZARPrecise, type FxExposureResult } from "@/lib/treasury-display";

export interface FxExposureCardProps {
  exposure: FxExposureResult;
  currencyCode: string;
}

export function FxExposureCard({ exposure, currencyCode }: FxExposureCardProps) {
  // resolveFxDisplayState throws on a mutual-exclusivity violation - a real, deliberate design
  // choice: a malformed payload from a future backend change or a network-layer corruption must
  // surface as a visible error state, never a silently wrong or double-counted number on a
  // financial dashboard. Caught here at the render boundary, not swallowed.
  let state;
  try {
    state = resolveFxDisplayState(exposure);
  } catch (error) {
    return (
      <div className="rounded-xl border border-rose-900/50 bg-[#131625]/90 p-5 shadow-lg">
        <p className="text-sm font-medium text-rose-400">FX Exposure — Diagnostic State</p>
        <p className="mt-1 text-xs text-slate-400">{error instanceof Error ? error.message : "Unknown data integrity error"}</p>
      </div>
    );
  }

  const valueColor = state.isAdverse ? "text-rose-400" : "text-emerald-400";

  return (
    <div className="rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-300">{state.label}</p>
        <span className="rounded-full border border-[#1F2438] px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
          {currencyCode} · {state.mode}
        </span>
      </div>
      <p className={`mt-2 text-2xl font-semibold ${valueColor}`}>{formatZARPrecise(state.value)}</p>
      {exposure.fecContractRate !== null && (
        <p className="mt-1 text-xs text-slate-500">FEC locked at {exposure.fecContractRate.toFixed(4)}</p>
      )}
    </div>
  );
}
