/**
 * Branding configuration layer - the single place tenant white-label config gets resolved.
 * Previously inlined directly in app/welcome/page.tsx; centralized here so any future page that
 * needs the active tenant's brand (a header logo, an email template, anything else) reads from
 * one function, not a second copy of the same env-var list that could drift out of sync.
 *
 * This is deployment-time white-labeling, not runtime multi-tenant branding - worth stating
 * plainly, not left implicit. NEXT_PUBLIC_* env vars are baked in at build time, so this
 * resolves to the SAME brand for every visitor of a given deployment, regardless of which
 * organisation they log in as - the standard "one build per reseller client" SaaS pattern, not
 * "the same running app shows different branding per logged-in tenant." Every other piece of
 * tenant data in this app (spend, contracts, rebates) is fetched from the backend after auth,
 * RLS-scoped per organisation - true "driven by the active tenant profile" branding would need
 * the same treatment (a real DB table + API route + fetch-on-login), not an env var. That's a
 * larger, separate piece of work, not silently built here instead of what was actually asked for.
 *
 * The core platform's own name ("ProcureIQ") is never resolved through this layer - it's not
 * tenant-configurable, by design (point 2 of this feature's own rules). This file only ever
 * touches the white-label splash screen's presentation, never any internal platform/API naming.
 */
import type { ClientBrand } from "@/types/client-brand";

// The real, current deployment's tenant - PPS Logistics - kept as the fallback-of-last-resort in
// exactly one place, not duplicated across every page that might want brand config. A future
// reseller deployment overrides every field below via env var; none of this is hardcoded into
// any component itself (HomeGateway.tsx and TruckTransition.tsx only ever read the ClientBrand
// object they're given as a prop - neither imports this file or PPS Logistics' name directly).
const CURRENT_DEPLOYMENT_DEFAULT_BRAND: ClientBrand = {
  name: "PPS Logistics",
  primaryColor: "#6366F1",
  truckImageSrc: "/images/pps-logistics-truck-side-removebg-preview.png",
  workerImageSrc: "/images/pps-logistics-worker-front-removebg-preview.png",
};

/**
 * Resolves the active deployment's white-label ClientBrand from environment variables, falling
 * back to the current deployment's real default per field - never a partial object, never
 * silently missing a field a component expects. Safe to call from a Server Component (reads
 * process.env directly, no client-only APIs) - app/welcome/page.tsx calls this at render time.
 */
export function resolveClientBrand(): ClientBrand {
  return {
    name: process.env.NEXT_PUBLIC_CLIENT_BRAND_NAME ?? CURRENT_DEPLOYMENT_DEFAULT_BRAND.name,
    primaryColor:
      process.env.NEXT_PUBLIC_CLIENT_BRAND_PRIMARY_COLOR ?? CURRENT_DEPLOYMENT_DEFAULT_BRAND.primaryColor,
    logoUrl: process.env.NEXT_PUBLIC_CLIENT_BRAND_LOGO_URL || undefined,
    logoAlt: process.env.NEXT_PUBLIC_CLIENT_BRAND_LOGO_ALT || undefined,
    truckImageSrc:
      process.env.NEXT_PUBLIC_CLIENT_BRAND_TRUCK_IMAGE_URL || CURRENT_DEPLOYMENT_DEFAULT_BRAND.truckImageSrc,
    workerImageSrc:
      process.env.NEXT_PUBLIC_CLIENT_BRAND_WORKER_IMAGE_URL || CURRENT_DEPLOYMENT_DEFAULT_BRAND.workerImageSrc,
  };
}
