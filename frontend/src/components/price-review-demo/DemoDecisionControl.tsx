/**
 * Buyer decision control for one demo line. Deliberately holds no state itself and calls no
 * apiFetch, ever - the decision lives in the parent page's React state only
 * (app/price-reviews/demo/analysis/page.tsx's `decisions` map) for exactly as long as the tab is
 * open. Nothing here writes to the backend, sessionStorage, or localStorage; there is no real
 * price-review record behind this demo for a decision to attach to. The "Demo-only" caption is
 * always visible, not just after a choice is made, so a buyer never mistakes a demo click for a
 * recorded one.
 */
"use client";

export type DemoDecision = "investigate" | "accept" | "negotiate";

const DECISION_LABELS: Record<DemoDecision, string> = {
  investigate: "Investigate",
  accept: "Accept",
  negotiate: "Negotiate",
};

const DECISION_ORDER: DemoDecision[] = ["investigate", "accept", "negotiate"];

interface DemoDecisionControlProps {
  lineId: string;
  decision: DemoDecision | null;
  onDecide: (lineId: string, decision: DemoDecision) => void;
}

export function DemoDecisionControl({ lineId, decision, onDecide }: DemoDecisionControlProps) {
  return (
    <div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Record a demo decision">
        {DECISION_ORDER.map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={decision === key}
            onClick={() => onDecide(lineId, key)}
            className={`rounded border px-3 py-1.5 text-xs font-medium ${
              decision === key
                ? "border-indigo-600 bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-[color:var(--app-surface-light-strong)]"
            }`}
          >
            {DECISION_LABELS[key]}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs font-medium text-amber-400">
        Demo-only — not saved to ProcureIQ.
        {decision ? ` Recorded locally as "${DECISION_LABELS[decision]}."` : ""}
      </p>
    </div>
  );
}
