"use client";

import { useEffect, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Skeleton } from "@/components/ui/skeleton";
import { formatZAR, spendAnalyticsApi, type MonthOverMonthPoint } from "@/lib/dashboard-api";

function DarkTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[#1F2438] bg-[#131625] px-3 py-2 text-xs shadow-lg">
      <p className="text-slate-400">{label}</p>
      <p className="mt-1 font-semibold text-slate-100">{formatZAR(payload[0].value)}</p>
    </div>
  );
}

export function SpendTrendChart() {
  const [data, setData] = useState<MonthOverMonthPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    spendAnalyticsApi
      .trend()
      .then((points) => {
        if (!cancelled) setData(points);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load spend trend");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
      <h3 className="text-slate-100 font-semibold">Spend & Contract Variance Trend</h3>
      <p className="text-slate-400 text-xs">Monthly spend, aggregated from purchase invoices and transactions</p>
      <div className="mt-4 h-72">
        {error ? (
          <p className="flex h-full items-center justify-center text-sm text-rose-400">{error}</p>
        ) : !data ? (
          <Skeleton className="h-full w-full" />
        ) : data.length === 0 ? (
          <p className="flex h-full items-center justify-center text-sm text-slate-500">No purchase data yet</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data.map((p) => ({ month: p.month, amount: Number(p.amount) }))}>
              <defs>
                <linearGradient id="spendFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366F1" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#6366F1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="month" tick={{ fill: "#94A3B8", fontSize: 11 }} axisLine={{ stroke: "#1F2438" }} tickLine={false} />
              <YAxis tick={{ fill: "#94A3B8", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => formatZAR(v)} />
              <Tooltip content={<DarkTooltip />} />
              <Area type="monotone" dataKey="amount" stroke="#6366F1" strokeWidth={2} fill="url(#spendFill)" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
