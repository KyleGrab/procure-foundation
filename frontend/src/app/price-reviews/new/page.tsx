/**
 * New review wizard, step 1-2 of spec Section 36's flow (Supplier -> Upload Price Lists).
 * Steps 3-9 (mapping/matches/analysis/negotiation) are their own routes so wizard progress
 * survives a page refresh (spec Section 36's explicit requirement) rather than living in
 * component state that vanishes on reload.
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { PriceReview } from "@/types/price-review";

const STEPS = ["Supplier", "Upload", "Map Columns", "Validate", "Match", "Review Matches", "Analyse", "Negotiate", "Complete"];

export default function NewPriceReviewPage() {
  const router = useRouter();
  const [supplierPublicId, setSupplierPublicId] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const token = sessionStorage.getItem("procureiq_access_token") ?? undefined;
    try {
      const review = await apiFetch<PriceReview>("/price-reviews", {
        method: "POST",
        accessToken: token,
        body: JSON.stringify({ supplier_public_id: supplierPublicId, currency: "ZAR", price_basis: "tax_exclusive" }),
      });
      router.push(`/price-reviews/${review.public_id}/mapping`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the review");
    }
  }

  return (
    <main className="mx-auto max-w-2xl p-8">
      <ol className="mb-8 flex flex-wrap gap-2 text-xs text-slate-500">
        {STEPS.map((step, i) => (
          <li key={step} className={i === 0 ? "font-semibold text-slate-900" : ""}>
            {i + 1}. {step}
          </li>
        ))}
      </ol>
      <h1 className="mb-4 text-xl font-semibold">New Price Review</h1>
      <form onSubmit={handleCreate} className="flex flex-col gap-3">
        <label className="text-sm text-slate-600">
          Supplier
          <input
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            placeholder="Supplier ID"
            value={supplierPublicId}
            onChange={(e) => setSupplierPublicId(e.target.value)}
            required
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="rounded bg-slate-900 px-4 py-2 text-white" type="submit">
          Create Review &amp; Continue to Upload
        </button>
      </form>
    </main>
  );
}
