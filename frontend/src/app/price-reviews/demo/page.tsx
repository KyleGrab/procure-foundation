/**
 * Illustrative Price Review walkthrough - overview (PROCUREIQ-PRICE-REVIEW-DEMO-UX-R2). Mirrors
 * the shape of the real /price-reviews/[id] overview page (status + links into each step) but is
 * a plain server component reading only the static DEMO_REVIEW - no apiFetch, no token, no
 * network call of any kind, since this walkthrough must never create, modify, or read a real
 * backend record.
 */
import Link from "next/link";
import { DEMO_REVIEW } from "@/lib/price-review-demo-data";

export default function PriceReviewDemoOverviewPage() {
  return (
    <main className="mx-auto max-w-3xl p-8">
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-indigo-300">Illustrative walkthrough</p>
      <h1 className="mb-1 text-xl font-semibold text-slate-100">Price Review — {DEMO_REVIEW.supplier_name}</h1>
      <p className="mb-6 text-sm text-slate-400">
        A made-up supplier and price list, walking through the same steps a real review would.
      </p>

      <dl className="mb-8 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div className="rounded border p-3">
          <dt className="text-slate-500">Increase received</dt>
          <dd className="text-lg font-semibold text-slate-100">{DEMO_REVIEW.received_at}</dd>
        </div>
        <div className="rounded border p-3">
          <dt className="text-slate-500">Status</dt>
          <dd className="text-lg font-semibold text-slate-100">{DEMO_REVIEW.status_label}</dd>
        </div>
        <div className="rounded border p-3">
          <dt className="text-slate-500">Effective date</dt>
          <dd className="text-lg font-semibold text-slate-100">{DEMO_REVIEW.effective_date}</dd>
        </div>
        <div className="rounded border p-3">
          <dt className="text-slate-500">Lines</dt>
          <dd className="text-lg font-semibold text-slate-100">{DEMO_REVIEW.line_count}</dd>
        </div>
      </dl>

      <Link
        href={DEMO_REVIEW.next_action_href}
        className="inline-block rounded bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-600"
      >
        {DEMO_REVIEW.next_action_label}
      </Link>

      <div className="mt-8 flex flex-col gap-2 text-sm">
        <Link href="/price-reviews/demo/analysis" className="rounded border p-3 hover:bg-[color:var(--app-surface-light-strong)]">
          Analysis &amp; investigation
        </Link>
        <Link href="/price-reviews/demo/negotiation" className="rounded border p-3 hover:bg-[color:var(--app-surface-light-strong)]">
          Negotiation
        </Link>
        <Link href="/price-reviews" className="rounded border p-3 text-slate-400 hover:bg-[color:var(--app-surface-light-strong)]">
          ← Back to Price Reviews
        </Link>
      </div>
    </main>
  );
}
