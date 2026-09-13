/**
 * Illustrative Price Review walkthrough - Analysis & Investigation
 * (PROCUREIQ-PRICE-REVIEW-DEMO-UX-R2). Combines the live app's separate Analysis
 * (/price-reviews/[id]/analysis) and uncertain-match review (/price-reviews/[id]/matches) steps
 * into one screen: the same clean line table, plus the filters and line-detail drawer the
 * "Investigation" step of the walkthrough calls for. Decisions recorded here
 * (DemoDecisionControl) live only in this page's own React state - never sent anywhere.
 */
"use client";

import { useState } from "react";
import Link from "next/link";
import type { PriceReviewLine } from "@/types/price-review";
import { DEMO_LINES, DEMO_REVIEW } from "@/lib/price-review-demo-data";
import { DemoAnalysisTable, type LineFilter } from "@/components/price-review-demo/DemoAnalysisTable";
import { LineDetailDrawer } from "@/components/price-review-demo/LineDetailDrawer";
import type { DemoDecision } from "@/components/price-review-demo/DemoDecisionControl";

export default function PriceReviewDemoAnalysisPage() {
  const [filter, setFilter] = useState<LineFilter>("all");
  const [selectedLine, setSelectedLine] = useState<PriceReviewLine | null>(null);
  const [decisions, setDecisions] = useState<Record<string, DemoDecision>>({});

  function handleDecide(lineId: string, decision: DemoDecision) {
    setDecisions((prev) => ({ ...prev, [lineId]: decision }));
  }

  return (
    <main className="mx-auto max-w-6xl p-8">
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Illustrative walkthrough</p>
      <h1 className="mb-2 text-xl font-semibold text-slate-900">
        Analysis &amp; investigation — {DEMO_REVIEW.supplier_name}
      </h1>
      <p className="mb-6 text-sm text-slate-600">
        Filter by investigation status, then open a line for its full detail and to record a
        demo-only decision.
      </p>

      <DemoAnalysisTable
        lines={DEMO_LINES}
        filter={filter}
        onFilterChange={setFilter}
        onSelectLine={setSelectedLine}
      />

      <LineDetailDrawer
        line={selectedLine}
        decision={selectedLine ? (decisions[selectedLine.public_id] ?? null) : null}
        onDecide={handleDecide}
        onClose={() => setSelectedLine(null)}
      />

      <div className="mt-8 flex gap-4 text-sm">
        <Link href="/price-reviews/demo" className="text-slate-600 underline hover:text-slate-900">
          ← Back to overview
        </Link>
        <Link href="/price-reviews/demo/negotiation" className="text-indigo-700 underline hover:text-indigo-900">
          Continue to negotiation →
        </Link>
      </div>
    </main>
  );
}
