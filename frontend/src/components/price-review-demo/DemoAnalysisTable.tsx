/**
 * Line table for the demo Analysis/Investigation screen. Filtering and formatting logic both
 * live in their own pure modules (price-review-line-classification.ts, decimal-display.ts) and
 * are unit-tested there directly; this component only wires them to markup, so its own test
 * (DemoAnalysisTable.test.tsx) can focus on what actually renders - null-as-"—", exact Decimal
 * strings, and the filter buttons - rather than re-deriving the classification/formatting logic.
 */
"use client";

import type { PriceReviewLine } from "@/types/price-review";
import { classifyLineForInvestigation, type InvestigationCategory } from "@/lib/price-review-line-classification";
import { formatDecimalCurrency, formatDecimalPercent, formatDecimalOrUnknown } from "@/lib/decimal-display";

export type LineFilter = InvestigationCategory | "all";

const FILTERS: { key: LineFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "needs_attention", label: "Needs attention" },
  { key: "matched", label: "Matched" },
  { key: "unknown", label: "Unknown" },
];

const ATTENTION_LABEL: Record<InvestigationCategory, string | null> = {
  needs_attention: "Needs attention",
  unknown: "Unknown",
  matched: null,
};

interface DemoAnalysisTableProps {
  lines: PriceReviewLine[];
  filter: LineFilter;
  onFilterChange: (filter: LineFilter) => void;
  onSelectLine: (line: PriceReviewLine) => void;
}

export function DemoAnalysisTable({ lines, filter, onFilterChange, onSelectLine }: DemoAnalysisTableProps) {
  const filtered =
    filter === "all" ? lines : lines.filter((line) => classifyLineForInvestigation(line) === filter);

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2 text-xs" role="group" aria-label="Filter lines by investigation status">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => onFilterChange(f.key)}
            className={`rounded border px-3 py-1 ${
              filter === f.key
                ? "border-indigo-600 bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-[color:var(--app-surface-light-strong)]"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b text-slate-500">
            <th className="py-2">Product</th>
            <th>Old price</th>
            <th>New price</th>
            <th>Change</th>
            <th>Match confidence</th>
            <th>Attention</th>
            <th className="sr-only">Details</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((line) => {
            const category = classifyLineForInvestigation(line);
            const attentionLabel = ATTENTION_LABEL[category];
            return (
              <tr key={line.public_id} className="border-b">
                <td className="py-2">
                  {formatDecimalOrUnknown(line.new_description ?? line.old_description)}
                </td>
                <td>{formatDecimalCurrency(line.old_price)}</td>
                <td>{formatDecimalCurrency(line.new_price)}</td>
                <td>{formatDecimalPercent(line.percentage_change)}</td>
                <td>{formatDecimalPercent(line.match_confidence, 0)}</td>
                <td>
                  {attentionLabel ? (
                    <span className={category === "needs_attention" ? "font-medium text-amber-400" : "font-medium text-slate-500"}>
                      {attentionLabel}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    onClick={() => onSelectLine(line)}
                    className="rounded px-2 py-1 text-indigo-300 underline hover:bg-indigo-950/30"
                  >
                    View
                  </button>
                </td>
              </tr>
            );
          })}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={7} className="py-6 text-center text-slate-500">
                No lines match this filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
