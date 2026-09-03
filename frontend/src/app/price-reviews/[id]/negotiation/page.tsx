/**
 * Negotiation targets + outcomes (spec Section 23-24) and the AI negotiation brief (Section 26).
 * The brief button calls a route that, in this delivery, has never been executed against a real
 * model (no network in the environment that built this - see
 * app/services/negotiation_brief_service.py). The UI still needs to make that honest: no fake
 * "generating..." shimmer implying a capability that hasn't been verified end to end.
 */
"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";

export default function NegotiationPage() {
  const params = useParams<{ id: string }>();
  const [brief, setBrief] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function generateBrief() {
    setLoading(true);
    setError(null);
    const token = sessionStorage.getItem("procureiq_access_token") ?? undefined;
    try {
      const result = await apiFetch<{ brief: string }>(`/price-reviews/${params.id}/negotiation-brief`, {
        method: "POST",
        accessToken: token,
      });
      setBrief(result.brief);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate the negotiation brief");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="mb-6 text-xl font-semibold">Negotiation</h1>
      <p className="mb-6 text-sm text-slate-600">
        Set target prices per line on the Analysis screen, then generate a negotiation brief
        summarising priorities and talking points from verified figures only.
      </p>
      <button onClick={generateBrief} disabled={loading} className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-40">
        {loading ? "Generating..." : "Generate Negotiation Brief"}
      </button>
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      {brief && <pre className="mt-6 whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-4 text-sm">{brief}</pre>}
    </main>
  );
}
