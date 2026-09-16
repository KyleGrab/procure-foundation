/**
 * Illustrative Price Review walkthrough - Negotiation (PROCUREIQ-PRICE-REVIEW-DEMO-UX-R2).
 *
 * Two clearly separate sections, on purpose: a static, clearly-labelled illustrative brief built
 * only from this walkthrough's own fabricated lines (never a real AI call - see
 * price-review-demo-data.ts's DEMO_NEGOTIATION_FOCUS_LINE_IDS), and a second control that, when
 * clicked, states plainly that a live AI brief is unavailable in demo mode rather than faking a
 * "generating..." shimmer or inventing brief text the way the real
 * /price-reviews/[id]/negotiation page's own docstring says it deliberately avoids. Nothing here
 * calls apiFetch or any network endpoint.
 */
"use client";

import { useState } from "react";
import Link from "next/link";
import { DEMO_REVIEW, findDemoLineById } from "@/lib/price-review-demo-data";
import { formatDecimalCurrency, formatDecimalPercent } from "@/lib/decimal-display";

const criticalIncrease = findDemoLineById("demo-line-02");
const confidentIncrease = findDemoLineById("demo-line-01");
const packChange = findDemoLineById("demo-line-03");

export default function PriceReviewDemoNegotiationPage() {
  const [liveBriefRequested, setLiveBriefRequested] = useState(false);

  return (
    <main className="mx-auto max-w-3xl p-8">
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-indigo-300">Illustrative walkthrough</p>
      <h1 className="mb-6 text-xl font-semibold text-slate-100">Negotiation — {DEMO_REVIEW.supplier_name}</h1>

      <section className="mb-8 rounded border p-4">
        <h2 className="mb-1 text-sm font-semibold text-slate-100">Illustrative negotiation brief (demo)</h2>
        <p className="mb-3 text-xs text-slate-500">
          Built from this walkthrough&apos;s own fabricated lines only — not AI-generated, and not
          based on any live supplier or customer data.
        </p>
        <ul className="list-disc space-y-3 pl-5 text-sm text-slate-300">
          {criticalIncrease && (
            <li>
              <span className="font-medium">{criticalIncrease.old_description}:</span> proposed
              increase of {formatDecimalPercent(criticalIncrease.percentage_change)} (
              {formatDecimalCurrency(criticalIncrease.old_price)} → {formatDecimalCurrency(criticalIncrease.new_price)}
              ), flagged <span className="font-medium text-amber-400">critical</span>. Ask for the
              underlying cost justification before accepting — this is the largest single swing
              in the review.
            </li>
          )}
          {confidentIncrease && (
            <li>
              <span className="font-medium">{confidentIncrease.old_description}:</span> a smaller,
              well-matched increase of {formatDecimalPercent(confidentIncrease.percentage_change)}.
              A reasonable opening position is a phased increase rather than accepting it in full
              immediately.
            </li>
          )}
          {packChange && (
            <li>
              <span className="font-medium">{packChange.old_description}:</span> pack size changed
              alongside the price and match confidence is only{" "}
              {formatDecimalPercent(packChange.match_confidence, 0)} — confirm the new pack is
              genuinely equivalent before treating this line&apos;s price change as comparable at
              all.
            </li>
          )}
        </ul>
      </section>

      <section className="rounded border border-dashed p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-100">Live AI negotiation brief</h2>
        <p className="mb-3 text-sm text-slate-400">
          The real negotiation-brief endpoint is available for a real review, not this
          illustrative walkthrough.
        </p>
        <button
          type="button"
          onClick={() => setLiveBriefRequested(true)}
          className="rounded border px-4 py-2 text-sm font-medium text-slate-300 hover:bg-[color:var(--app-surface-light-strong)]"
        >
          Generate live AI brief
        </button>
        {liveBriefRequested && (
          <p role="status" className="mt-3 text-sm font-medium text-amber-400">
            Live AI brief unavailable in demo mode.
          </p>
        )}
      </section>

      <div className="mt-8 flex gap-4 text-sm">
        <Link href="/price-reviews/demo/analysis" className="text-slate-400 underline hover:text-slate-100">
          ← Back to analysis
        </Link>
        <Link href="/price-reviews/demo" className="text-slate-400 underline hover:text-slate-100">
          ← Back to overview
        </Link>
      </div>
    </main>
  );
}
