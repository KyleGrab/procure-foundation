"use client";

import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { formatZAR, spendAnalyticsApi, type TopPriceIncrease } from "@/lib/dashboard-api";

export function TopSupplierIncreases() {
  const [items, setItems] = useState<TopPriceIncrease[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    spendAnalyticsApi
      .topPriceIncreases(8)
      .then((data) => {
        if (!cancelled) setItems(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load price increases");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const maxImpact = items?.length
    ? Math.max(...items.map((i) => Math.abs(Number(i.annual_impact ?? 0))))
    : 1;

  return (
    <div className="rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
      <h3 className="text-slate-100 font-semibold">Top Supplier Increases</h3>
      <p className="text-slate-400 text-xs">Ranked by annual financial impact</p>
      <div className="mt-4 space-y-4">
        {error ? (
          <p className="text-sm text-rose-400">{error}</p>
        ) : !items ? (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)
        ) : items.length === 0 ? (
          <p className="text-sm text-slate-500">No price increases recorded yet</p>
        ) : (
          items.map((item, i) => {
            const impact = Math.abs(Number(item.annual_impact ?? 0));
            const widthPct = maxImpact > 0 ? (impact / maxImpact) * 100 : 0;
            return (
              <div key={i}>
                <div className="flex items-baseline justify-between">
                  <span className="text-sm text-slate-200 truncate">{item.supplier}</span>
                  <span className="text-xs text-slate-400">{formatZAR(impact)}</span>
                </div>
                <p className="truncate text-xs text-slate-500">{item.product}</p>
                <div className="mt-1 h-1.5 w-full rounded-full bg-indigo-500/20">
                  <div className="h-1.5 rounded-full bg-indigo-500" style={{ width: `${widthPct}%` }} />
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
