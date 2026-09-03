/**
 * Supplier review summary / overview (spec Section 35 /price-reviews/{id}) - status and links
 * into each wizard step, so a returning user lands somewhere useful rather than back at step 1.
 */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { PriceReview } from "@/types/price-review";

export default function PriceReviewOverviewPage() {
  const params = useParams<{ id: string }>();
  const [review, setReview] = useState<PriceReview | null>(null);

  useEffect(() => {
    const token = sessionStorage.getItem("procureiq_access_token") ?? undefined;
    apiFetch<PriceReview>(`/price-reviews/${params.id}`, { accessToken: token }).then(setReview).catch(() => setReview(null));
  }, [params.id]);

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="mb-2 text-xl font-semibold">Price Review</h1>
      <p className="mb-6 text-sm text-slate-600">Status: {review?.status ?? "loading..."}</p>
      <div className="flex flex-col gap-2 text-sm">
        <Link href={`/price-reviews/${params.id}/mapping`} className="rounded border p-3 hover:bg-slate-50">Upload &amp; Map Columns</Link>
        <Link href={`/price-reviews/${params.id}/matches`} className="rounded border p-3 hover:bg-slate-50">Review Uncertain Matches</Link>
        <Link href={`/price-reviews/${params.id}/analysis`} className="rounded border p-3 hover:bg-slate-50">View Analysis</Link>
        <Link href={`/price-reviews/${params.id}/negotiation`} className="rounded border p-3 hover:bg-slate-50">Negotiation</Link>
      </div>
    </main>
  );
}
