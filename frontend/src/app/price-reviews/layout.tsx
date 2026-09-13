/**
 * Shared shell for every /price-reviews/* route (history list, new-review wizard, per-review
 * wizard steps, and the illustrative demo walkthrough nested under it) - PROCUREIQ-APP-BACKGROUND-R1.
 *
 * The app's shared background (app/layout.tsx's AppBackground) is dark by default, but every page
 * in this subtree was already written assuming a light, opaque background and dark text (confirmed
 * by grep across every page.tsx here before this was added, not assumed) - their tables, forms,
 * and headings never set their own bg/text color at the page-root level. Rather than touching each
 * page's markup, decimal rendering, or classes individually, this one shared panel provides the
 * exact light, opaque surface they already depend on, framed by the same dark app background
 * everywhere else - "appropriate opaque surfaces for data-dense content" applied at the one place
 * that covers every route here at once, not duplicated per page.
 *
 * app/price-reviews/demo/layout.tsx (nested under this one) had its own bg-white wrapper before
 * this change; that's removed in favour of this shared panel so the two don't double-nest.
 */
export default function PriceReviewsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen px-4 py-6 sm:px-8 sm:py-10">
      <div className="mx-auto max-w-6xl overflow-hidden rounded-2xl border border-[#1F2438] bg-white text-slate-900 shadow-2xl">
        {children}
      </div>
    </div>
  );
}
