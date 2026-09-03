/**
 * Main analysis table (spec Section 20-21) + supplier summary (Section 19). Ranked by financial
 * impact by default per Section 15 - percentage-only sorting is available but never the default,
 * since a 3% increase on R10m matters more than a 40% increase on R2,000.
 */
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { PriceReviewLine, SupplierSummary } from "@/types/price-review";

export default function AnalysisPage() {
  const params = useParams<{ id: string }>();
  const [lines, setLines] = useState<PriceReviewLine[]>([]);
  const [summary, setSummary] = useState<SupplierSummary | null>(null);
  const [filter, setFilter] = useState<"all" | "increases" | "critical" | "pack_changed">("all");

  useEffect(() => {
    const token = sessionStorage.getItem("procureiq_access_token") ?? undefined;
    apiFetch<PriceReviewLine[]>(`/price-reviews/${params.id}/lines`, { accessToken: token }).then(setLines).catch(() => setLines([]));
    apiFetch<SupplierSummary>(`/price-reviews/${params.id}/summary`, { accessToken: token }).then(setSummary).catch(() => setSummary(null));
  }, [params.id]);

  const filtered = lines
    .filter((l) => {
      if (filter === "increases") return l.movement_type === "price_increase";
      if (filter === "critical") return l.risk_classification === "critical";
      if (filter === "pack_changed") return l.movement_type === "pack_change";
      return true;
    })
    .sort((a, b) => Math.abs(Number(b.annual_impact ?? 0)) - Math.abs(Number(a.annual_impact ?? 0)));

  return (
    <main className="mx-auto max-w-6xl p-8">
      <h1 className="mb-6 text-xl font-semibold">Price Review Analysis</h1>

      {summary && (
        <div className="mb-6 grid grid-cols-4 gap-4 text-sm">
          <div className="rounded border p-3"><p className="text-slate-500">Weighted Avg Increase</p><p className="text-lg font-semibold">{summary.weighted_average_price_increase_pct ? `${(Number(summary.weighted_average_price_increase_pct) * 100).toFixed(1)}%` : "—"}</p></div>
          <div className="rounded border p-3"><p className="text-slate-500">Annual Cost Impact</p><p className="text-lg font-semibold">R{Number(summary.annual_cost_impact).toLocaleString()}</p></div>
          <div className="rounded border p-3"><p className="text-slate-500">Pack Changes</p><p className="text-lg font-semibold">{summary.pack_changes}</p></div>
          <div className="rounded border p-3"><p className="text-slate-500">Needs Review</p><p className="text-lg font-semibold">{summary.products_requiring_manual_review}</p></div>
        </div>
      )}

      <div className="mb-4 flex gap-2 text-xs">
        {(["all", "increases", "critical", "pack_changed"] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)} className={`rounded border px-3 py-1 ${filter === f ? "bg-slate-900 text-white" : ""}`}>
            {f}
          </button>
        ))}
      </div>

      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b text-slate-500">
            <th className="py-2">Product</th><th>Old Price</th><th>New Price</th><th>Change %</th>
            <th>Annual Impact</th><th>Risk</th><th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((l) => (
            <tr key={l.public_id} className="border-b">
              <td className="py-2">{l.new_description ?? l.old_description}</td>
              <td>R{l.old_price}</td>
              <td>R{l.new_price}</td>
              <td>{l.percentage_change ? `${(Number(l.percentage_change) * 100).toFixed(1)}%` : "—"}</td>
              <td>{l.annual_impact ? `R${Number(l.annual_impact).toLocaleString()}` : "—"}</td>
              <td>{l.risk_classification ?? "—"}</td>
              <td>{l.buyer_decision ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
