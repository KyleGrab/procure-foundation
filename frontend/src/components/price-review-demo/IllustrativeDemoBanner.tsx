/**
 * Persistent banner shown on every /price-reviews/demo/* page (rendered once, in
 * app/price-reviews/demo/layout.tsx, rather than copied into each page). `role="status"` so
 * assistive tech announces it without requiring focus, and it's a static child of the page flow
 * rather than a dismissible toast - the walkthrough must never be viewable without it.
 *
 * Colours retinted dark under PROCUREIQ-BLUE-SURFACE-R2 to sit on the now-dark Price Review
 * panel - same amber warning semantic the rest of the app already uses for this (the login page's
 * "Dev only" panel, Procurement Command Centre's AlertTriangle rows), not a new colour invented
 * for this banner.
 */
export function IllustrativeDemoBanner() {
  return (
    <div role="status" className="border-b border-amber-700/50 bg-amber-950/20 px-4 py-2 text-center text-sm font-medium text-amber-300">
      Illustrative demo data — not live supplier or customer data.
    </div>
  );
}
