"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { shouldShowDevDemoLogin } from "@/lib/dev-demo-guard";
import { shouldShowDemoLoginBypass } from "@/lib/demo-login-bypass-guard";
import type { TokenPair } from "@/types/auth";

// Dev-only, explicitly temporary per direct instruction - to be removed before production.
// NOT a login bypass: this pre-fills the real form with a real seeded user's real credentials
// (backend/app/db/seeds/dev_demo_credentials.py) and still submits through the exact same
// POST /auth/login flow as any other login - real password check, real JWT issuance, real RLS
// scoping. shouldShowDevDemoLogin (tested, src/lib/dev-demo-guard.test.ts) is the one and only
// gate controlling visibility - never shown unless NODE_ENV is exactly "development".
const DEV_DEMO_EMAIL = "dev-demo@procureiq.local";
const DEV_DEMO_PASSWORD = "dev-demo-only-not-for-production";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  // PROCUREIQ-DEMO-LOGIN-SINGLE-ENTRY-R1: when both flags are set, this is a local presentation
  // machine - the page must show only the Illustrative demo entry point below, not a second,
  // real-looking login form beside it. Reuses shouldShowDemoLoginBypass's own stricter AND gate
  // (NODE_ENV==="development" AND NEXT_PUBLIC_DEMO_MODE==="true") rather than a new condition, so
  // this can never drift out of sync with the one guard that already decides whether the demo
  // entry point itself is shown - same underlying case computed once, not two independent checks
  // that could disagree.
  const isFullDemoMode = shouldShowDemoLoginBypass(process.env.NODE_ENV, process.env.NEXT_PUBLIC_DEMO_MODE);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const tokens = await apiFetch<TokenPair>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      // Phase 1: access token held in a parent auth context, not persisted here.
      // See lib/api.ts for why this deliberately avoids localStorage.
      sessionStorage.setItem("procureiq_access_token", tokens.access_token);
      router.push("/welcome");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    }
  }

  function fillDevDemoCredentials() {
    setEmail(DEV_DEMO_EMAIL);
    setPassword(DEV_DEMO_PASSWORD);
  }

  // Distinct from fillDevDemoCredentials above: that button still submits through the real
  // POST /auth/login flow against a seeded backend user, for testing real auth. This one is a
  // genuine client-only bypass - it never calls apiFetch and never fabricates an access token -
  // for touring the illustrative Price Review walkthrough on a machine with no backend running
  // at all (see docs/runbook.md's "no network access confirmed" caveat). Any real,
  // authentication-requiring page a demo visitor navigates to afterwards (Management Accounting,
  // Operations, or Procurement's live canvas data) is left completely alone by this: with no
  // token in sessionStorage, those honestly fail exactly as they would for anyone unauthenticated
  // - never a forged session pretending to be real. Gated by shouldShowDemoLoginBypass below,
  // which requires NODE_ENV==="development" AND NEXT_PUBLIC_DEMO_MODE==="true" together - see
  // that function's own docstring for why this needs a stricter, dedicated guard rather than
  // reusing isDemoModeEnabled's OR semantics.
  function handleDemoSignIn() {
    sessionStorage.removeItem("procureiq_access_token");
    router.push("/welcome");
  }

  return (
    // PROCUREIQ-APP-BACKGROUND-R1: no longer paints its own flat bg-[#0B0D17] here - the shared
    // root layout (app/layout.tsx) is dark by default now, with the same indigo glow /welcome
    // already had, so this page picks that up automatically and, for the first time, actually
    // matches the gateway it leads into rather than a flatter stand-in for it. register/page.tsx
    // got the equivalent dark-card treatment (border-[#1F2438]/bg-[#131625] inputs, text-white
    // heading) as a direct consequence of this same change - the root body's text color is no
    // longer implicitly dark, so its previously-unstyled heading needed the explicit color this
    // page's own heading already had.
    <main className="min-h-screen px-6 py-24">
      <div className="mx-auto max-w-sm">
        {/* Normal production authentication form - the entire section, heading included, only
            for the case this page isn't acting as a local presentation machine (see
            isFullDemoMode above). Unchanged in every other respect: same fields, same styling,
            same handleSubmit/real POST /auth/login flow. */}
        {!isFullDemoMode && (
          <>
            <h1 className="mb-6 text-xl font-semibold text-white">Log in</h1>
            <form onSubmit={handleSubmit} className="flex flex-col gap-3">
              <input
                className="rounded border border-[#1F2438] bg-[#131625] px-3 py-2 text-white placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
                type="email"
                placeholder="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
              <input
                className="rounded border border-[#1F2438] bg-[#131625] px-3 py-2 text-white placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              {error && <p className="text-sm text-rose-400">{error}</p>}
              <button className="rounded bg-indigo-500 px-4 py-2 text-white hover:bg-indigo-600" type="submit">
                Log in
              </button>
            </form>
          </>
        )}

        {shouldShowDemoLoginBypass(process.env.NODE_ENV, process.env.NEXT_PUBLIC_DEMO_MODE) && (
          <div className="mt-6 rounded border border-dashed border-indigo-500/40 bg-indigo-950/20 p-3">
            <p className="text-xs font-medium text-indigo-300">Illustrative demo</p>
            <p className="mt-1 text-xs text-slate-400">
              Skip sign-in and tour the illustrative Price Review walkthrough — no real account, no
              live supplier or customer data.
            </p>
            <button
              type="button"
              onClick={handleDemoSignIn}
              className="mt-2 w-full rounded border border-indigo-500/40 px-3 py-1.5 text-sm font-medium text-indigo-300 hover:bg-indigo-900/20 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              Continue with demo sign-in
            </button>
          </div>
        )}

        {/* Also excluded from the local-demo-machine case (isFullDemoMode) below - the page must
            show only the Illustrative demo panel then, per PROCUREIQ-DEMO-LOGIN-SINGLE-ENTRY-R1.
            Unaffected in ordinary local development (demo mode not enabled), where this keeps
            its existing behavior exactly. */}
        {shouldShowDevDemoLogin(process.env.NODE_ENV) && !isFullDemoMode && (
          <div className="mt-6 rounded border border-dashed border-amber-700/50 bg-amber-950/20 p-3">
            <p className="text-xs text-amber-400">Dev only - not shown in production</p>
            <button
              type="button"
              onClick={fillDevDemoCredentials}
              className="mt-2 w-full rounded border border-amber-700/50 px-3 py-1.5 text-sm text-amber-300 hover:bg-amber-900/20"
            >
              Use demo credentials
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
