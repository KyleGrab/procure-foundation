"use client";

import { useEffect, useState } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { formatZAR, spendAnalyticsApi, savingsRegisterApi } from "@/lib/dashboard-api";

interface MetricCardProps {
  label: string;
  value: string | null;
  loading: boolean;
  trend?: { direction: "up" | "down"; text: string };
  badge?: { variant: "positive" | "alert"; text: string };
}

function MetricCard({ label, value, loading, trend, badge }: MetricCardProps) {
  return (
    <div className="rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
      <p className="text-xs text-slate-400">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-8 w-32" />
      ) : (
        <p className="mt-1 text-2xl font-bold text-slate-100">{value}</p>
      )}
      <div className="mt-2 flex items-center gap-2">
        {trend && !loading && (
          <span className={`flex items-center gap-1 text-xs ${trend.direction === "up" ? "text-emerald-400" : "text-rose-400"}`}>
            {trend.direction === "up" ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {trend.text}
          </span>
        )}
        {badge && !loading && <Badge variant={badge.variant}>{badge.text}</Badge>}
      </div>
    </div>
  );
}

/**
 * Four cards per the spec. Two figures don't map cleanly to a single existing endpoint response,
 * so they're derived here from what the backend actually returns rather than invented:
 * "PPV Leakage Identified" sums annual_impact across top price increases (a proxy for a dedicated
 * PPV aggregate endpoint, which doesn't exist yet - noted, not hidden). "Gross Margin Erosion
 * Rate" isn't computable at all without selling-price data this dashboard has no source for
 * (price_review lines only carry margin fields when sales data was supplied at review time) -
 * shown as "No data" with an explanatory badge rather than a fabricated percentage.
 */
export function MetricRibbon() {
  const [loading, setLoading] = useState(true);
  const [totalSpend, setTotalSpend] = useState<number | null>(null);
  const [spendChangePct, setSpendChangePct] = useState<number | null>(null);
  const [ppvLeakage, setPpvLeakage] = useState<number | null>(null);
  const [realisedSavings, setRealisedSavings] = useState<number | null>(null);
  const [opportunityCount, setOpportunityCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [spendItems, trend, topIncreases, savings] = await Promise.all([
          spendAnalyticsApi.bySupplier(),
          spendAnalyticsApi.trend(),
          spendAnalyticsApi.topPriceIncreases(20),
          savingsRegisterApi.list(),
        ]);
        if (cancelled) return;

        const total = spendItems.reduce((sum, i) => sum + Number(i.amount), 0);
        setTotalSpend(total);

        const lastPoint = trend[trend.length - 1];
        setSpendChangePct(lastPoint?.change_pct ? Number(lastPoint.change_pct) * 100 : null);

        const leakage = topIncreases.reduce((sum, i) => sum + Number(i.annual_impact ?? 0), 0);
        setPpvLeakage(leakage);

        const realisedOpportunities = savings.filter(
          (o) => o.status === "realised" && ["calculated", "confirmed"].includes(o.realised_savings_status)
        );
        setRealisedSavings(realisedOpportunities.reduce((sum, o) => sum + Number(o.realised_savings), 0));
        setOpportunityCount(realisedOpportunities.length);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load dashboard metrics");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-400">{error}</div>
    );
  }

  return (
    <div className="grid grid-cols-4 gap-4">
      <MetricCard
        label="Total Addressable Spend"
        value={totalSpend !== null ? formatZAR(totalSpend) : null}
        loading={loading}
        trend={
          spendChangePct !== null
            ? { direction: spendChangePct >= 0 ? "up" : "down", text: `${spendChangePct.toFixed(1)}% vs last month` }
            : undefined
        }
      />
      <MetricCard
        label="PPV Leakage Identified"
        value={ppvLeakage !== null ? formatZAR(ppvLeakage) : null}
        loading={loading}
        badge={ppvLeakage !== null && ppvLeakage > 0 ? { variant: "alert", text: "High Priority" } : undefined}
      />
      <MetricCard
        label="Gross Margin Erosion Rate"
        value="No data"
        loading={loading}
        badge={{ variant: "alert", text: "Requires selling-price data" }}
      />
      <MetricCard
        label="Verified Savings Realised"
        value={realisedSavings !== null ? formatZAR(realisedSavings) : null}
        loading={loading}
        badge={{ variant: "positive", text: `${opportunityCount} opportunities` }}
      />
    </div>
  );
}
