/**
 * Persistent banner shown on every /price-reviews/demo/* page (rendered once, in
 * app/price-reviews/demo/layout.tsx, rather than copied into each page). `role="status"` so
 * assistive tech announces it without requiring focus, and it's a static child of the page flow
 * rather than a dismissible toast - the walkthrough must never be viewable without it.
 */
export function IllustrativeDemoBanner() {
  return (
    <div role="status" className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-sm font-medium text-amber-900">
      Illustrative demo data — not live supplier or customer data.
    </div>
  );
}
