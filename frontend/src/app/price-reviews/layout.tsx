/**
 * Shared shell for every /price-reviews/* route (history list, new-review wizard, per-review
 * wizard steps, and the illustrative demo walkthrough nested under it) - PROCUREIQ-APP-BACKGROUND-R1,
 * retinted under PROCUREIQ-BLUE-SURFACE-R1, then again under R2.
 *
 * The app's shared background (app/layout.tsx's AppBackground) is dark; this panel now matches it
 * instead of sitting on top of it as a separate light block - components/ui/LightSurface.tsx is
 * the same translucent bg-[#131625]/90 + border-[#1F2438] treatment the Welcome gateway and
 * Procurement Command Centre already use, so a page in this subtree reads as part of one
 * consistent app rather than a light insert dropped onto a dark one.
 *
 * app/price-reviews/demo/layout.tsx (nested under this one) had its own bg-white wrapper before
 * PROCUREIQ-APP-BACKGROUND-R1; that's removed in favour of this shared panel so the two don't
 * double-nest.
 */
import { LightSurface } from "@/components/ui/LightSurface";

export default function PriceReviewsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen px-4 py-6 sm:px-8 sm:py-10">
      <LightSurface className="mx-auto max-w-6xl overflow-hidden rounded-2xl shadow-2xl">
        {children}
      </LightSurface>
    </div>
  );
}
