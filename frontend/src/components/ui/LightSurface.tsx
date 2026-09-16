/**
 * The app's blue surface system for the Price Review subtree (PROCUREIQ-BLUE-SURFACE-R1,
 * retinted dark under R2) - a translucent indigo/navy panel, the same bg-[#131625]/90 +
 * border-[#1F2438] treatment the Welcome gateway and Procurement Command Centre already use
 * (see components/gateway/HomeGateway.tsx, app/dashboard/procurement/page.tsx), rather than the
 * near-white surface this originally held - Price Reviews is no longer the one part of the app
 * still built on a light background.
 *
 * Reused by app/price-reviews/layout.tsx (the one shared panel for the whole Price Review
 * subtree) and by LineDetailDrawer.tsx (the drawer's own panel) - the two places in this app that
 * need an opaque, legible surface floating on the dark app background, so both draw from the same
 * tokens (globals.css's --app-surface-light/--app-border-light) instead of each hardcoding its
 * own color.
 */
import type { HTMLAttributes } from "react";

export function LightSurface({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`border border-[color:var(--app-border-light)] bg-[color:var(--app-surface-light)] text-slate-100 backdrop-blur-sm ${className}`}
      {...props}
    />
  );
}
