/**
 * Human match review (spec Section 10) - side-by-side previous/proposed-new item, confidence,
 * and the four required actions. No uncertain match is ever treated as authoritative until
 * resolved here (enforced server-side too, not just by this UI - see
 * app.matching.review.is_authoritative).
 */
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { PriceReviewLine } from "@/types/price-review";

export default function MatchesPage() {
  const params = useParams<{ id: string }>();
  const [lines, setLines] = useState<PriceReviewLine[]>([]);

  useEffect(() => {
    const token = sessionStorage.getItem("procureiq_access_token") ?? undefined;
    apiFetch<PriceReviewLine[]>(`/price-reviews/${params.id}/lines`, { accessToken: token })
      .then((all) => setLines(all.filter((l) => l.match_status === "review_required")))
      .catch(() => setLines([]));
  }, [params.id]);

  async function decide(linePublicId: string, action: string) {
    const token = sessionStorage.getItem("procureiq_access_token") ?? undefined;
    await apiFetch(`/price-reviews/${params.id}/lines/${linePublicId}/match-decision`, {
      method: "POST",
      accessToken: token,
      body: JSON.stringify({ action }),
    });
    setLines((prev) => prev.filter((l) => l.public_id !== linePublicId));
  }

  return (
    <main className="mx-auto max-w-5xl p-8">
      <h1 className="mb-2 text-xl font-semibold">Review Uncertain Matches</h1>
      <p className="mb-6 text-sm text-slate-600">{lines.length} item(s) need a decision before analysis.</p>
      <div className="flex flex-col gap-4">
        {lines.map((line) => (
          <div key={line.public_id} className="rounded border border-slate-300 p-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="font-medium">Previous</p>
                <p>{line.old_description}</p>
                <p className="text-slate-500">{line.old_pack_raw} · R{line.old_price}</p>
              </div>
              <div>
                <p className="font-medium">Proposed New</p>
                <p>{line.new_description}</p>
                <p className="text-slate-500">{line.new_pack_raw} · R{line.new_price}</p>
              </div>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Confidence: {line.match_confidence ? (Number(line.match_confidence) * 100).toFixed(0) : "?"}%
            </p>
            <div className="mt-3 flex gap-2">
              <button onClick={() => decide(line.public_id, "confirm")} className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white">
                Confirm Match
              </button>
              <button onClick={() => decide(line.public_id, "mark_new")} className="rounded border px-3 py-1.5 text-xs">
                Mark as New Product
              </button>
              <button onClick={() => decide(line.public_id, "mark_discontinued")} className="rounded border px-3 py-1.5 text-xs">
                Mark as Discontinued
              </button>
              <button onClick={() => decide(line.public_id, "ignore")} className="rounded border px-3 py-1.5 text-xs text-slate-500">
                Ignore
              </button>
            </div>
          </div>
        ))}
        {lines.length === 0 && <p className="text-slate-500">No matches currently need review.</p>}
      </div>
    </main>
  );
}
