/**
 * Pure guard controlling whether the dev-only demo-credentials button renders on the login page.
 * Deliberately its own small, explicit, tested function rather than an inline JSX condition -
 * given this specific gate exists to prevent a demo-credentials shortcut from ever appearing in
 * production, it gets the same "structural, not just discouraged" treatment as this codebase's
 * other security-relevant guards (revenue_basis, is_fallback_rate's removed defaults) rather
 * than being buried where a future edit could silently invert or remove it unnoticed.
 */

export function shouldShowDevDemoLogin(nodeEnv: string | undefined): boolean {
  return nodeEnv === "development";
}
