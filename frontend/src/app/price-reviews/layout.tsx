/**
 * Shared shell for every /price-reviews/* route (history list, new-review wizard, per-review
 * wizard steps, and the illustrative demo walkthrough nested under it) - PROCUREIQ-APP-BACKGROUND-R1,
 * retinted under PROCUREIQ-BLUE-SURFACE-R1.
 *
 * The app's shared background (app/layout.tsx's AppBackground) is dark by default, but every page
 * in this subtree was already written assuming a light, opaque background and dark text (confirmed
 * by grep across every page.tsx here before this was added, not assumed) - their tables, forms,
 * and headings never set their own bg/text color at the page-root level. This shared panel gives
 * them the light, opaque surface they already depend on, using components/ui/LightSurface.tsx -
 * the app's softly blue-tinted light surface, not a plain white block - framed by the same dark
 * app background everywhere else.
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
