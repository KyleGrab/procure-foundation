"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { TokenPair } from "@/types/auth";

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
    <main className="mx-auto mt-16 max-w-sm">
      <h1 className="mb-6 text-xl font-semibold">Register your organisation</h1>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <input
          className="rounded border border-slate-300 px-3 py-2"
          placeholder="First name"
          onChange={(e) => update("first_name", e.target.value)}
          required
        />
        <input
          className="rounded border border-slate-300 px-3 py-2"
          placeholder="Last name"
          onChange={(e) => update("last_name", e.target.value)}
          required
        />
        <input
          className="rounded border border-slate-300 px-3 py-2"
          type="email"
          placeholder="Work email"
          onChange={(e) => update("email", e.target.value)}
          required
        />
        <input
          className="rounded border border-slate-300 px-3 py-2"
          type="password"
          placeholder="Password (min 12 characters)"
          onChange={(e) => update("password", e.target.value)}
          required
        />
        <input
          className="rounded border border-slate-300 px-3 py-2"
          placeholder="Organisation name"
          onChange={(e) => update("organisation_name", e.target.value)}
          required
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="rounded bg-slate-900 px-4 py-2 text-white" type="submit">
          Create account
        </button>
      </form>
    </main>
  );
}
