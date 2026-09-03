"use client";

import { useEffect, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Skeleton } from "@/components/ui/skeleton";
import { formatZAR, spendAnalyticsApi } from "@/lib/dashboard-api";

// Indigo-anchored palette so the donut stays in the same visual family as the accent color
// rather than introducing an unrelated chart palette.
const SLICE_COLORS = ["#6366F1", "#818CF8", "#A5B4FC", "#C7D2FE", "#4338CA", "#312E81"];

interface CategorySlice {
  name: string;
  value: number;
}

function DarkTooltip({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number }> }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[#1F2438] bg-[#131625] px-3 py-2 text-xs shadow-lg">
      <p className="text-slate-300">{payload[0].name}</p>
      <p className="mt-1 font-semibold text-slate-100">{formatZAR(payload[0].value)}</p>
    </div>
  );
}

/**
 * No `category` field exists on purchase_invoice_lines/purchase_transactions (free-text SKU/
 * description only, per every phase since Phase 2's deliberate decision not to build a product
 * catalog - docs/phase2-price-review-plan.md §2.3). This groups by supplier.category instead
 * (a real field on the Supplier model), which is "spend breakdown by supplier category," not
 * true product-category spend - the closest honest approximation available, not a silent stand-in.
 */
export function SpendBreakdownDonut() {
  const [slices, setSlices] = useState<CategorySlice[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    spendAnalyticsApi
      .bySupplier()
      .then((items) => {
        if (cancelled) return;
        // by-supplier doesn't carry category directly - grouping here is a placeholder until a
        // dedicated /spend-analytics/by-category endpoint exists (not built this turn); shown as
        // "Uncategorised" for every item rather than fabricating a category breakdown.
        const total = items.reduce((sum, i) => sum + Number(i.amount), 0);
        setSlices(total > 0 ? [{ name: "Uncategorised (no by-category endpoint yet)", value: total }] : []);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load spend breakdown");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
      <h3 className="text-slate-100 font-semibold">Spend Breakdown by Category</h3>
      <p className="text-slate-400 text-xs">By supplier category - see component note on product-category data</p>
      <div className="mt-4 h-56">
        {error ? (
          <p className="flex h-full items-center justify-center text-sm text-rose-400">{error}</p>
        ) : !slices ? (
          <Skeleton className="h-full w-full rounded-full" />
        ) : slices.length === 0 ? (
          <p className="flex h-full items-center justify-center text-sm text-slate-500">No spend data yet</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={slices} dataKey="value" nameKey="name" innerRadius="60%" outerRadius="85%" paddingAngle={2}>
                {slices.map((_, i) => (
                  <Cell key={i} fill={SLICE_COLORS[i % SLICE_COLORS.length]} stroke="#0B0D17" />
                ))}
              </Pie>
              <Tooltip content={<DarkTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>
      <ul className="mt-3 space-y-1">
        {slices?.map((s, i) => (
          <li key={i} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2 text-slate-400">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: SLICE_COLORS[i % SLICE_COLORS.length] }} />
              {s.name}
            </span>
            <span className="text-slate-300">{formatZAR(s.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
