/**
 * Pure guard controlling whether the "Continue with demo sign-in" bypass renders on the login
 * page (app/login/page.tsx) - and, since that block is the only place handleDemoSignIn is
 * reachable from, the only guard standing between a visitor and skipping real authentication
 * entirely.
 *
 * Deliberately its own function, NOT a reuse of demo-mode.ts's isDemoModeEnabled. That one uses
 * OR (NODE_ENV === "development" OR NEXT_PUBLIC_DEMO_MODE === "true") and stays correct for what
 * it actually gates: the read-only illustrative Price Review walkthrough's entry points
 * (/price-reviews's own link, the Procurement lens callout, and the /price-reviews/demo route
 * tree's own notFound() gate) - none of those create a session, touch authentication, or send
 * anything to the backend, so either signal alone being enough is the correct, deliberate design
 * the original spec asked for ("local development, or when an explicit NEXT_PUBLIC_DEMO_MODE=true
 * flag is set").
 *
 * A login bypass is different in kind, not degree. It skips the real form and drops any existing
 * session (see handleDemoSignIn) - a single leaked or misconfigured NEXT_PUBLIC_DEMO_MODE=true in
 * a real deployment must never be enough on its own to expose it, and a shared "development-like"
 * preview environment that isn't a real `next dev` process must never accidentally qualify either.
 * Both signals are required:
 *
 *   NODE_ENV === "development"  AND  NEXT_PUBLIC_DEMO_MODE === "true"
 *
 * `next build` / `next start` always set NODE_ENV to "production" - there is no way to make this
 * true in a production build or a production server process, regardless of how
 * NEXT_PUBLIC_DEMO_MODE is set at build time. Verified directly against a real
 * `NEXT_PUBLIC_DEMO_MODE=true npm run build && npm run start`, not just asserted from reading this
 * file - see login/page.production.test.tsx and this feature's own verification report.
 */

export function shouldShowDemoLoginBypass(
  nodeEnv: string | undefined,
  demoModeFlag: string | undefined,
): boolean {
  return nodeEnv === "development" && demoModeFlag === "true";
}
