"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { shouldShowDevDemoLogin } from "@/lib/dev-demo-guard";
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

  return (
    <main className="mx-auto mt-24 max-w-sm">
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

      {shouldShowDevDemoLogin(process.env.NODE_ENV) && (
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
    </main>
  );
}
