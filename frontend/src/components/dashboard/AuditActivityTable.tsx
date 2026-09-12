"use client";

import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { opportunitiesApi } from "@/lib/dashboard-api";

interface ActivityRow {
  publicId: string;
  description: string;
  type: "duplicate_sku" | "consolidation";
  score: string;
  status: string;
}

const STATUS_BADGE: Record<string, BadgeVariant> = {
  flagged: "pending",
  confirmed_duplicate: "verified",
  consolidation_recommended: "verified",
  rejected: "rejected",
  under_review: "pending",
};

/**
 * "Recent Audit Activity" per the spec - sourced from duplicate-SKU and supplier-consolidation
 * flags (app.services.duplicate_detection_service), since those are exactly spec §107/§22's
 * human-review-required flags, the closest real data this backend has to an "approve/reject a
 * finding" audit feed. Every action here calls the real, published review endpoint for its flag
 * type (spec's own never-silently-merge principle - confirming here doesn't auto-merge suppliers,
 * reassign anything, or write a financial fact; it only records the human decision, same as the
 * backend's own docstrings say). Duplicate-SKU flags are a binary confirm/reject
 * (reviewDuplicateSkuFlag); consolidation flags are a 3-state action
 * (reviewConsolidationFlag - CONSOLIDATION-REVIEW-UI-R1) since spec §22 treats consolidation as a
 * broader human workflow, not a yes/no.
 */
export function AuditActivityTable() {
  const [rows, setRows] = useState<ActivityRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actioning, setActioning] = useState<string | null>(null);

  async function load() {
    try {
      const [duplicates, consolidations] = await Promise.all([
        opportunitiesApi.duplicateSkuFlags() as Promise<Array<{ public_id: string; description_a: string; description_b: string; similarity_score: string; status: string }>>,
        opportunitiesApi.consolidationFlags() as Promise<Array<{ public_id: string; description_a: string; description_b: string; similarity_score: string; status: string }>>,
      ]);
      const combined: ActivityRow[] = [
        ...duplicates.map((d) => ({
          publicId: d.public_id, description: `${d.description_a} ↔ ${d.description_b}`,
          type: "duplicate_sku" as const, score: d.similarity_score, status: d.status,
        })),
        ...consolidations.map((c) => ({
          publicId: c.public_id, description: `${c.description_a} ↔ ${c.description_b}`,
          type: "consolidation" as const, score: c.similarity_score, status: c.status,
        })),
      ];
      setRows(combined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load audit activity");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleDuplicateSkuDecision(row: ActivityRow, confirmed: boolean) {
    setActioning(row.publicId);
    try {
      await opportunitiesApi.reviewDuplicateSkuFlag(row.publicId, confirmed);
      await load(); // re-fetch from the backend - never guess the resulting status client-side
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record the review decision");
    } finally {
      setActioning(null);
    }
  }

  // CONSOLIDATION-REVIEW-UI-R1: wires the real, published review route
  // (POST /opportunities/consolidation-flags/{id}/review) via opportunitiesApi.reviewConsolidationFlag
  // - a 3-state action (mark_under_review/recommend_consolidation/reject), not a binary confirm
  // the way duplicate-SKU flags work, since spec §22 treats consolidation as a broader human
  // workflow (service risk, geographic coverage, supply resilience). Records a review decision
  // only - never merges suppliers, reassigns anything, or writes a financial fact; the backend's
  // own state machine (app.analytics.domain_graph) is the sole authority on which transitions are
  // valid, and 409s from it surface here as the same safe, structured error message apiFetch
  // already extracts for every other action in this table.
  async function handleConsolidationDecision(
    row: ActivityRow, action: "mark_under_review" | "recommend_consolidation" | "reject",
  ) {
    setActioning(row.publicId);
    setError(null);
    try {
      await opportunitiesApi.reviewConsolidationFlag(row.publicId, action);
      await load(); // re-fetch from the backend - never guess the resulting status client-side
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record the review decision");
    } finally {
      setActioning(null);
    }
  }

  return (
    <div className="rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
      <h3 className="text-slate-100 font-semibold">Recent Audit Activity</h3>
      <p className="text-slate-400 text-xs">Duplicate-SKU and supplier-consolidation flags pending review</p>
      <div className="mt-4">
        {error ? (
          <p className="text-sm text-rose-400">{error}</p>
        ) : !rows ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : rows.length === 0 ? (
          <p className="text-sm text-slate-500">No pending flags - run a duplicate-SKU or consolidation scan to populate this</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Finding</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.publicId}>
                  <TableCell className="max-w-xs truncate">{row.description}</TableCell>
                  <TableCell className="text-xs text-slate-400">
                    {row.type === "duplicate_sku" ? "Duplicate SKU" : "Supplier Consolidation"}
                  </TableCell>
                  <TableCell className="text-xs">{(Number(row.score) * 100).toFixed(0)}%</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_BADGE[row.status] ?? "neutral"}>{row.status.replace("_", " ")}</Badge>
                  </TableCell>
                  <TableCell>
                    {row.status !== "flagged" ? (
                      <span className="text-xs text-slate-600">—</span>
                    ) : row.type === "duplicate_sku" ? (
                      <div className="flex gap-2">
                        <button
                          disabled={actioning === row.publicId}
                          onClick={() => handleDuplicateSkuDecision(row, true)}
                          title="Approve"
                          className="rounded-md border border-emerald-500/20 bg-emerald-500/10 p-1 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40"
                          aria-label="Approve"
                        >
                          <Check className="h-3.5 w-3.5" />
                        </button>
                        <button
                          disabled={actioning === row.publicId}
                          onClick={() => handleDuplicateSkuDecision(row, false)}
                          title="Reject"
                          className="rounded-md border border-rose-500/20 bg-rose-500/10 p-1 text-rose-400 hover:bg-rose-500/20 disabled:opacity-40"
                          aria-label="Reject"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        <button
                          disabled={actioning === row.publicId}
                          onClick={() => handleConsolidationDecision(row, "mark_under_review")}
                          title="Records a review decision only - does not merge suppliers, reassign anything, or write a financial fact"
                          className="rounded-md border border-[#1F2438] bg-[#0B0D17] px-2 py-1 text-[11px] text-slate-300 hover:border-indigo-500/40 hover:text-indigo-400 disabled:opacity-40"
                        >
                          Mark under review
                        </button>
                        <button
                          disabled={actioning === row.publicId}
                          onClick={() => handleConsolidationDecision(row, "recommend_consolidation")}
                          title="Records a review decision only - does not merge suppliers, reassign anything, or write a financial fact"
                          className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40"
                        >
                          Recommend consolidation
                        </button>
                        <button
                          disabled={actioning === row.publicId}
                          onClick={() => handleConsolidationDecision(row, "reject")}
                          title="Records a review decision only - does not merge suppliers, reassign anything, or write a financial fact"
                          className="rounded-md border border-rose-500/20 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-400 hover:bg-rose-500/20 disabled:opacity-40"
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
