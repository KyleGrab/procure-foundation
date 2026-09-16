/**
 * Shared shell for every /price-reviews/demo/* page: the structural, server-side gate
 * (PROCUREIQ-PRICE-REVIEW-DEMO-UX-R2 requires this route tree never appear automatically in a
 * production deployment) plus the persistent illustrative-data banner every demo page must show.
 *
 * This is a plain server component (no "use client") specifically so the gate runs before
 * anything renders, on every request, and can't be bypassed by navigating straight to a
 * /price-reviews/demo/* URL - hiding the "Open illustrative walkthrough" link on /price-reviews
 * (DemoWalkthroughEntry) is only the UX-level half of this; this notFound() call is the real,
 * structural control, same relationship as shouldShowRegistrationLink has to the backend's own
 * RegistrationDisabledError.
 *
 * PROCUREIQ-APP-BACKGROUND-R1: dropped this layout's own `min-h-screen bg-white` wrapper - the
 * parent app/price-reviews/layout.tsx now provides that one opaque panel for the whole subtree;
 * keeping a second one here would have nested a full-viewport-height white div inside that
 * already-bounded, rounded panel, breaking its rounded corners.
 */
import { notFound } from "next/navigation";
import { isDemoModeEnabled } from "@/lib/demo-mode";
import { IllustrativeDemoBanner } from "@/components/price-review-demo/IllustrativeDemoBanner";

export default function PriceReviewDemoLayout({ children }: { children: React.ReactNode }) {
  if (!isDemoModeEnabled(process.env.NODE_ENV, process.env.NEXT_PUBLIC_DEMO_MODE)) {
    notFound();
  }

  return (
    <>
      <IllustrativeDemoBanner />
      {children}
    </>
  );
}
