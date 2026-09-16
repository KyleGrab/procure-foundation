/**
 * The light half of the app's blue surface system (PROCUREIQ-BLUE-SURFACE-R1) - a softly
 * indigo-tinted, opaque panel for dense, data-heavy content that needs to stay light-on-dark-text
 * for legibility (financial review tables/forms) rather than the dark bg-[#131625]/text-slate-100
 * surface used everywhere else in the app (see components/ui/table.tsx, the dashboard cards).
 *
 * Reused by app/price-reviews/layout.tsx (the one shared panel for the whole Price Review
 * subtree) and by LineDetailDrawer.tsx (the drawer's own panel) - the two places in this app that
 * need an opaque, legible surface floating on the dark app background, so both draw from the same
 * tokens (globals.css's --app-surface-light/--app-border-light) instead of each hardcoding its
 * own near-white.
 */
import type { HTMLAttributes } from "react";

export function LightSurface({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`border border-[color:var(--app-border-light)] bg-[color:var(--app-surface-light)] text-slate-900 ${className}`}
      {...props}
    />
  );
}
