/**
 * Line-detail side panel for the demo Investigation flow. A simple accessible dialog rather than
 * a dependency: `role="dialog"`/`aria-modal`, focus moves to the close button on open, Escape and
 * the backdrop both close it, and closing returns keyboard focus to the row's own "View" button
 * (native browser behavior once the trigger element still exists after the drawer unmounts, so
 * no bespoke focus-restoration code is needed here).
 */
"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { PriceReviewLine } from "@/types/price-review";
import { classifyLineForInvestigation } from "@/lib/price-review-line-classification";
import { formatDecimalCurrency, formatDecimalPercent, formatDecimalOrUnknown } from "@/lib/decimal-display";
import { DemoDecisionControl, type DemoDecision } from "./DemoDecisionControl";

interface LineDetailDrawerProps {
  line: PriceReviewLine | null;
  decision: DemoDecision | null;
  onDecide: (lineId: string, decision: DemoDecision) => void;
  onClose: () => void;
}

export function LineDetailDrawer({ line, decision, onDecide, onClose }: LineDetailDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!line) return;
    closeButtonRef.current?.focus();
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [line, onClose]);

  if (!line) return null;

  const category = classifyLineForInvestigation(line);

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="demo-line-detail-heading"
        className="relative flex h-full w-full max-w-md flex-col overflow-y-auto border-l bg-[color:var(--app-surface-light)] p-6 text-slate-900 shadow-xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="demo-line-detail-heading" className="text-base font-semibold text-slate-900">
            {formatDecimalOrUnknown(line.new_description ?? line.old_description)}
          </h2>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close line detail"
            className="shrink-0 rounded p-1 text-slate-500 hover:bg-[color:var(--app-surface-light-strong)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <dl className="mt-6 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt className="text-slate-500">Old price</dt>
            <dd className="font-medium text-slate-900">{formatDecimalCurrency(line.old_price)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">New price</dt>
            <dd className="font-medium text-slate-900">{formatDecimalCurrency(line.new_price)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Change</dt>
            <dd className="font-medium text-slate-900">{formatDecimalPercent(line.percentage_change)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Match confidence</dt>
            <dd className="font-medium text-slate-900">{formatDecimalPercent(line.match_confidence, 0)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Old pack</dt>
            <dd className="font-medium text-slate-900">{formatDecimalOrUnknown(line.old_pack_raw)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">New pack</dt>
            <dd className="font-medium text-slate-900">{formatDecimalOrUnknown(line.new_pack_raw)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Annual impact</dt>
            <dd className="font-medium text-slate-900">{formatDecimalCurrency(line.annual_impact)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Investigation status</dt>
            <dd className="font-medium text-slate-900">
              {category === "needs_attention" ? "Needs attention" : category === "unknown" ? "Unknown" : "Matched"}
            </dd>
          </div>
        </dl>

        <div className="mt-6 border-t pt-4">
          <h3 className="mb-2 text-sm font-medium text-slate-900">Record a decision</h3>
          <DemoDecisionControl lineId={line.public_id} decision={decision} onDecide={onDecide} />
        </div>
      </div>
    </div>
  );
}
