/**
 * Root landing page - rebuilt to match the app's actual dark tokens. Was still the Phase 1
 * light-mode stub (text-slate-600, bg-slate-900 plain buttons) - the first thing anyone saw,
 * immediately followed by the polished dark /welcome gateway post-login. Caught while auditing
 * the frontend for polish gaps, not assumed fine because it compiled.
 */
import Link from "next/link";
import { shouldShowRegistrationLink } from "@/lib/registration-guard";

export default function HomePage() {
  const showRegistration = shouldShowRegistrationLink(process.env.NEXT_PUBLIC_ALLOW_SELF_REGISTRATION);
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#0B0D17] px-6">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ background: "radial-gradient(600px circle at 50% 30%, rgba(99,102,241,0.10), transparent 60%)" }}
      />
      <div className="relative z-10 text-center">
        <h1 className="text-3xl font-semibold text-slate-100">ProcureIQ</h1>
        <p className="mt-2 text-sm text-slate-400">Procurement intelligence and margin protection.</p>
        <div className="mt-8 flex justify-center gap-3">
          <Link
            href="/login"
            className="rounded-md bg-indigo-500 px-5 py-2.5 text-sm font-medium text-white shadow-[0_0_20px_rgba(99,102,241,0.25)] hover:bg-indigo-400"
          >
            Log in
          </Link>
          {showRegistration && (
            <Link
              href="/register"
              className="rounded-md border border-[#1F2438] bg-[#131625]/90 px-5 py-2.5 text-sm font-medium text-slate-300 hover:border-indigo-500/40 hover:text-slate-100"
            >
              Register organisation
            </Link>
          )}
        </div>
      </div>
    </main>
  );
}
