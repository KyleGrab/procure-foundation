/**
 * The one global ProcureIQ application background - the exact dark base color + indigo radial
 * glow previously duplicated, byte-for-byte identical, in app/page.tsx and
 * components/gateway/HomeGateway.tsx (both used `bg-[#0B0D17]` plus the exact same
 * `radial-gradient(600px circle at 50% 30%, rgba(99,102,241,0.10), transparent 60%)` inline
 * style - see globals.css's --app-bg-base/--app-bg-glow, the single source of truth for both
 * values now). Nothing invented: this is that same look, extracted once.
 *
 * Rendered here, once, in the root layout (app/layout.tsx) outside of `{children}` - Next.js's
 * App Router never unmounts anything in a layout that a client-side navigation stays under, so
 * this `fixed` div is never removed or repainted between routes. That's what actually prevents a
 * flash of an unstyled background between pages, not any per-page styling choice.
 *
 * No motion of any kind - there was none in what this replaces to preserve. The background it's
 * based on was always a single static gradient; this doesn't add animation that wasn't already
 * there, so there's nothing for prefers-reduced-motion to need to disable.
 *
 * Purely decorative and inert (aria-hidden, pointer-events-none), sits behind every page's own
 * content at z-index -10. A page needing an opaque, legible surface for dense tables/forms (e.g.
 * app/price-reviews/layout.tsx's white panel) simply paints its own background on top of this;
 * nothing here forces transparency on anything downstream.
 */
export function AppBackground() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 bg-[color:var(--app-bg-base)]">
      <div className="absolute inset-0" style={{ backgroundImage: "var(--app-bg-glow)" }} />
    </div>
  );
}
