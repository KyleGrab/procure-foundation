/**
 * Pure guard controlling whether the illustrative Price Review walkthrough is reachable at all -
 * both the "Open illustrative walkthrough" entry link on /price-reviews and the /price-reviews/demo
 * route tree itself (see app/price-reviews/demo/layout.tsx, which calls this before rendering
 * anything and 404s otherwise). Same "structural, not just discouraged" treatment as this
 * codebase's other visibility guards (dev-demo-guard.ts's shouldShowDevDemoLogin,
 * registration-guard.ts's shouldShowRegistrationLink): one small, explicit, tested function
 * rather than an inline condition a future edit could silently widen.
 *
 * Visible in local development (NODE_ENV === "development") OR when a deployment has explicitly
 * opted in via NEXT_PUBLIC_DEMO_MODE=true. Never visible by default in a production build - the
 * two inputs are independent env vars, not a single toggle, so a demo deployment can enable this
 * without also being in dev mode.
 */

export function isDemoModeEnabled(nodeEnv: string | undefined, demoModeFlag: string | undefined): boolean {
  return nodeEnv === "development" || demoModeFlag === "true";
}
