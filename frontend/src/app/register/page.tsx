"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { TokenPair } from "@/types/auth";

// PROCUREIQ-APP-BACKGROUND-R1: this page previously had no dark styling at all - a plain
// text-slate-300-implied heading and light border-slate-300 inputs, relying entirely on the root
// layout's old bg-slate-50 default to stay legible. Now that the shared root background is dark
// by default (app/layout.tsx), those unstyled elements would have rendered dark-on-dark. Given
// the exact same dark-card treatment login/page.tsx already uses (same input classes, same
// heading color, same button) - "user-credentials" per this feature's brief plainly includes
// registration, and reusing login's own styling exactly avoids inventing a second, slightly
// different dark theme for what is functionally the same kind of page.
export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    password: "",
    organisation_name: "",
  });
  const [error, setError] = useState<string | null>(null);

  function update(field: keyof typeof form, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const tokens = await apiFetch<TokenPair>("/auth/register", {
        method: "POST",
        body: JSON.stringify(form),
      });
      sessionStorage.setItem("procureiq_access_token", tokens.access_token);
      // Was router.push("/onboarding") - that page was never built (the original spec's 10-step
      // onboarding wizard, Section 50, was always out of scope for this delivery) - caught while
      // writing the production runbook and fixed here rather than documented as a workaround,
      // since it's a one-line fix and the alternative is a 404 on exactly the flow being
      // smoke-tested. Now points to /welcome (the gateway) instead of straight to /dashboard,
      // matching login's own redirect - a brand-new org should land on the workspace picker too.
      router.push("/welcome");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    }
  }

  return (
    <main className="min-h-screen px-6 py-24">
      <div className="mx-auto max-w-sm">
        <h1 className="mb-6 text-xl font-semibold text-white">Register your organisation</h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            className="rounded border border-[#1F2438] bg-[#131625] px-3 py-2 text-white placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
            placeholder="First name"
            onChange={(e) => update("first_name", e.target.value)}
            required
          />
          <input
            className="rounded border border-[#1F2438] bg-[#131625] px-3 py-2 text-white placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
            placeholder="Last name"
            onChange={(e) => update("last_name", e.target.value)}
            required
          />
          <input
            className="rounded border border-[#1F2438] bg-[#131625] px-3 py-2 text-white placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
            type="email"
            placeholder="Work email"
            onChange={(e) => update("email", e.target.value)}
            required
          />
          <input
            className="rounded border border-[#1F2438] bg-[#131625] px-3 py-2 text-white placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
            type="password"
            placeholder="Password (min 12 characters)"
            onChange={(e) => update("password", e.target.value)}
            required
          />
          <input
            className="rounded border border-[#1F2438] bg-[#131625] px-3 py-2 text-white placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
            placeholder="Organisation name"
            onChange={(e) => update("organisation_name", e.target.value)}
            required
          />
          {error && <p className="text-sm text-rose-400">{error}</p>}
          <button className="rounded bg-indigo-500 px-4 py-2 text-white hover:bg-indigo-600" type="submit">
            Create account
          </button>
        </form>
      </div>
    </main>
  );
}
