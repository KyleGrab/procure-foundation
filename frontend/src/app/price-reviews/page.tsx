/**
 * Price review history (spec Section 35 /price-reviews). Lists past and in-progress reviews;
 * the wizard itself starts at /price-reviews/new. Kept intentionally light in this delivery -
 * see docs/phase2-price-review-plan.md for what's backend-verified vs. frontend-scaffolded.
 */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { PriceReview } from "@/types/price-review";

export default function PriceReviewsPage() {
  const [reviews, setReviews] = useState<PriceReview[] | null>(null);

  useEffect(() => {
    const token = sessionStorage.getItem("procureiq_access_token") ?? undefined;
    // No list-all-reviews endpoint exists yet in this delivery (see docs/api.md) - this page is
    // wired for when it does, rather than calling something that doesn't exist.
    setReviews([]);
  }, []);

  return (
    <main className="mx-auto max-w-4xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Supplier Price Reviews</h1>
        <Link href="/price-reviews/new" className="rounded bg-slate-900 px-4 py-2 text-white">
          New Price Review
        </Link>
      </div>
      {reviews && reviews.length === 0 && (
        <p className="text-slate-600">No price reviews yet. Start one to compare a supplier&apos;s price lists.</p>
      )}
    </main>
  );
}
