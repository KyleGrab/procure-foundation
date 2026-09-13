/**
 * Demo-only call to action shown on the real Procurement lens (components/canvas/ProcureIQCanvas.tsx,
 * activeLens === "procurement") - routes into the Procurement Command Centre
 * (app/dashboard/procurement/page.tsx), the hub that itself hosts the primary "Open illustrative
 * price review" CTA plus a secondary link into Price Reviews history. Previously linked straight
 * to /price-reviews/demo; PROCUREIQ-PROCUREMENT-COMMAND-CENTRE-R1 inserts the Command Centre as
 * the intended stop between the lens and the walkthrough, so this callout's copy and destination
 * changed with it. Still a second discovery path into that journey alongside /price-reviews' own
 * "Open illustrative walkthrough" link (DemoWalkthroughEntry.tsx) and the Command Centre's own
 * Sidebar nav entry - the walkthrough is never reachable only via a bare URL.
 *
 * Gated by the same isDemoModeEnabled guard as every other demo entry point - invisible in a
 * production deployment with no NEXT_PUBLIC_DEMO_MODE flag, so real customers on the real
 * Procurement lens see no change at all. Renders before the canvas's own data fetch resolves (it
 * doesn't depend on canvasApi in any way), so it's never blocked by - or confused with - that
 * live, backend-dependent panel underneath it.
 */
"use client";

import Link from "next/link";
import { isDemoModeEnabled } from "@/lib/demo-mode";

interface ProcurementLensDemoCalloutProps {
  nodeEnv?: string;
  demoModeFlag?: string;
}

export function ProcurementLensDemoCallout({
  nodeEnv = process.env.NODE_ENV,
  demoModeFlag = process.env.NEXT_PUBLIC_DEMO_MODE,
}: ProcurementLensDemoCalloutProps) {
  if (!isDemoModeEnabled(nodeEnv, demoModeFlag)) return null;

  return (
    <div className="mt-6 flex flex-col gap-3 rounded-xl border border-dashed border-indigo-500/30 bg-indigo-500/5 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-indigo-300">Illustrative demo</p>
        <p className="mt-1 text-sm text-slate-300">
          Walk a complete procurement decision journey end to end — illustrative data only, no
          live supplier or customer data.
        </p>
      </div>
      <Link
        href="/dashboard/procurement"
        className="inline-flex shrink-0 items-center justify-center rounded-md bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-300"
      >
        Open Procurement Command Centre
      </Link>
    </div>
  );
}
