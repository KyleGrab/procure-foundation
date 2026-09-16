/**
 * "Open illustrative walkthrough" entry link on /price-reviews. Gated by the same
 * isDemoModeEnabled guard the /price-reviews/demo route tree itself checks server-side
 * (app/price-reviews/demo/layout.tsx) - hiding this link is UX only, exactly like
 * shouldShowRegistrationLink's own docstring says about its link; the layout's notFound() call
 * is the real, structural control that keeps this out of a production deployment even if someone
 * navigates to the URL directly.
 *
 * nodeEnv/demoModeFlag default to the real env vars for normal use; accepting them as optional
 * props (rather than reading process.env inline, the pattern this repo's other guards use) is
 * deliberate here so a test can render this component under both env states directly, without
 * mutating global process.env in a shared test runner.
 */
"use client";

import Link from "next/link";
import { isDemoModeEnabled } from "@/lib/demo-mode";

interface DemoWalkthroughEntryProps {
  nodeEnv?: string;
  demoModeFlag?: string;
}

export function DemoWalkthroughEntry({
  nodeEnv = process.env.NODE_ENV,
  demoModeFlag = process.env.NEXT_PUBLIC_DEMO_MODE,
}: DemoWalkthroughEntryProps) {
  if (!isDemoModeEnabled(nodeEnv, demoModeFlag)) return null;

  return (
    <Link
      href="/price-reviews/demo"
      className="rounded border border-dashed px-4 py-2 text-sm text-slate-300 hover:bg-[color:var(--app-surface-light-strong)]"
    >
      Open illustrative walkthrough
    </Link>
  );
}
