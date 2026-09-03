/**
 * Supplier Consolidation Graph (spec §22). Renders the node-edge payload from
 * GET /opportunities/consolidation-graph exactly as returned - this page computes zero
 * relationship/weight logic of its own, only presentation. Node/edge *positions* (x/y) are
 * computed here client-side (a simple deterministic circular layout, no new layout-engine
 * dependency) because the pure backend engine (app/analytics/domain_graph.py, §2.1) deliberately
 * never computes coordinates - its job is topology and a provenance-tracked weight, nothing
 * about where to draw it. That boundary is the actual point of this page's split from the
 * backend, not an implementation detail.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { formatZAR, opportunitiesApi, type DomainGraph, type GraphEdge } from "@/lib/dashboard-api";

const STATUS_BADGE: Record<string, BadgeVariant> = {
  flagged: "pending",
  under_review: "pending",
  consolidation_recommended: "verified",
  rejected: "rejected",
};

function layoutNodesInACircle(graph: DomainGraph): Node[] {
  const radius = Math.max(180, graph.nodes.length * 40);
  const center = radius + 80;
  return graph.nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(graph.nodes.length, 1);
    return {
      id: n.id,
      position: { x: center + radius * Math.cos(angle), y: center + radius * Math.sin(angle) },
      data: { label: n.label },
      style: {
        background: "#131625",
        border: "1px solid #1F2438",
        borderRadius: "10px",
        color: "#F1F5F9",
        fontSize: "12px",
        padding: "8px 12px",
        boxShadow: "0 0 20px rgba(99,102,241,0.15)",
      },
    };
  });
}

function toReactFlowEdges(graph: DomainGraph): Edge[] {
  return graph.edges.map((e, i) => ({
    id: `edge-${i}`,
    source: e.source_id,
    target: e.target_id,
    label: `${(Number(e.weight) < 1 ? (Number(e.weight) * 100).toFixed(0) + "%" : formatZAR(Number(e.weight)))}`,
    style: { stroke: "#6366F1", strokeWidth: 1.5 },
    labelStyle: { fill: "#94A3B8", fontSize: 10 },
    animated: e.status === "flagged",
  }));
}

export default function ConsolidationGraphPage() {
  const [graph, setGraph] = useState<DomainGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [selectedEdgeIndex, setSelectedEdgeIndex] = useState<number | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    opportunitiesApi
      .consolidationGraph()
      .then((data) => {
        if (!cancelled) setGraph(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load the consolidation graph");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const nodes = useMemo(() => (graph ? layoutNodesInACircle(graph) : []), [graph]);
  const edges = useMemo(() => (graph ? toReactFlowEdges(graph) : []), [graph]);

  function handleEdgeClick(_: React.MouseEvent, edge: Edge) {
    const index = Number(edge.id.replace("edge-", ""));
    const raw = graph?.edges[index];
    if (raw) {
      setSelectedEdge(raw);
      setSelectedEdgeIndex(index);
      setReviewError(null);
    }
  }

  async function handleReview(action: "mark_under_review" | "recommend_consolidation" | "reject") {
    if (!selectedEdge || selectedEdgeIndex === null || !graph) return;
    setReviewing(true);
    setReviewError(null);
    try {
      const result = await opportunitiesApi.reviewConsolidationFlag(selectedEdge.flag_public_id, action);
      // Update the edge in place - no refetch, per the request that this happen live without a
      // full page refresh. The backend already validated the transition (§7.3's pure state
      // machine); this just reflects what it confirmed actually happened.
      const updatedEdges = graph.edges.map((e, i) =>
        i === selectedEdgeIndex ? { ...e, status: result.status } : e
      );
      const updatedGraph = { ...graph, edges: updatedEdges };
      setGraph(updatedGraph);
      setSelectedEdge(updatedEdges[selectedEdgeIndex]);
    } catch (err) {
      // A 409 here means the pure state machine rejected the transition (e.g. reviewing an
      // already-terminal flag) - shown as an error, never silently ignored or retried.
      setReviewError(err instanceof Error ? err.message : "Could not update this flag's status");
    } finally {
      setReviewing(false);
    }
  }

  return (
    <main className="relative flex-1 p-6">
      <h1 className="text-slate-100 font-semibold">Supplier Consolidation Opportunities</h1>
          <p className="mt-1 text-slate-400 text-xs">
            Suppliers connected here were flagged (spec §22) as offering similar or equivalent
            items - a flag, never a recommendation. Service risk, geographic coverage, and supply
            resilience aren&apos;t visible to this graph and must be weighed by a person before
            any consolidation actually happens.
          </p>

          {error && (
            <div className="mt-6 rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-400">
              {error}
            </div>
          )}

          {!error && !graph && <Skeleton className="mt-6 h-[600px] w-full rounded-xl" />}

          {!error && graph && graph.nodes.length === 0 && (
            <div className="mt-6 rounded-xl border border-[#1F2438] bg-[#131625]/90 p-8 text-center text-sm text-slate-500 shadow-lg backdrop-blur-sm">
              No consolidation flags yet - run a consolidation scan
              (<code className="text-slate-400">POST /opportunities/consolidation-scan</code>) once
              there&apos;s purchase data for more than one supplier.
            </div>
          )}

          {!error && graph && graph.nodes.length > 0 && (
            <div className="mt-6 h-[600px] rounded-xl border border-[#1F2438] bg-[#131625]/60 shadow-lg backdrop-blur-sm">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onEdgeClick={handleEdgeClick}
                fitView
                proOptions={{ hideAttribution: true }}
              >
                <Background color="#1F2438" gap={24} />
                <Controls className="[&>button]:bg-[#131625] [&>button]:border-[#1F2438] [&>button]:text-slate-300" />
                <MiniMap
                  style={{ backgroundColor: "#0B0D17" }}
                  maskColor="rgba(11,13,23,0.7)"
                  nodeColor="#6366F1"
                />
              </ReactFlow>
            </div>
          )}

          {selectedEdge && (
            <aside className="fixed right-6 top-24 w-80 rounded-xl border border-[#1F2438] bg-[#131625]/95 p-5 shadow-lg backdrop-blur-sm">
              <div className="flex items-start justify-between">
                <h2 className="text-slate-100 font-semibold text-sm">Consolidation Flag</h2>
                <button onClick={() => setSelectedEdge(null)} className="text-slate-500 hover:text-slate-300 text-xs">
                  close
                </button>
              </div>
              <div className="mt-3 space-y-2 text-xs">
                <p className="text-slate-400">{selectedEdge.description_a}</p>
                <p className="text-slate-400">↕</p>
                <p className="text-slate-400">{selectedEdge.description_b}</p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-slate-500">Status</span>
                  <Badge variant={STATUS_BADGE[selectedEdge.status] ?? "neutral"}>
                    {selectedEdge.status.replace("_", " ")}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Similarity score</span>
                  <span className="text-slate-200">{(Number(selectedEdge.similarity_score) * 100).toFixed(0)}%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Matched via</span>
                  <span className="text-slate-200">{selectedEdge.match_method.replace(/_/g, " ")}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Combined spend</span>
                  <span className="text-slate-200">
                    {selectedEdge.combined_spend ? formatZAR(Number(selectedEdge.combined_spend)) : "Not available"}
                  </span>
                </div>
              </div>

              {reviewError && (
                <p className="mt-3 rounded-md border border-rose-500/20 bg-rose-500/10 p-2 text-xs text-rose-400">
                  {reviewError}
                </p>
              )}

              {selectedEdge.status === "consolidation_recommended" || selectedEdge.status === "rejected" ? (
                <p className="mt-4 text-xs text-slate-500">
                  This flag has reached a final decision and can&apos;t be reviewed further.
                </p>
              ) : (
                <div className="mt-4 space-y-2">
                  {selectedEdge.status === "flagged" && (
                    <button
                      onClick={() => handleReview("mark_under_review")}
                      disabled={reviewing}
                      className="w-full rounded-md border border-[#1F2438] bg-[#131625] px-3 py-2 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-indigo-400 disabled:opacity-40"
                    >
                      Mark Under Review
                    </button>
                  )}
                  <button
                    onClick={() => handleReview("recommend_consolidation")}
                    disabled={reviewing}
                    className="w-full rounded-md bg-emerald-500/10 border border-emerald-500/20 px-3 py-2 text-xs text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40"
                  >
                    Recommend Consolidation
                  </button>
                  <button
                    onClick={() => handleReview("reject")}
                    disabled={reviewing}
                    className="w-full rounded-md bg-rose-500/10 border border-rose-500/20 px-3 py-2 text-xs text-rose-400 hover:bg-rose-500/20 disabled:opacity-40"
                  >
                    Reject
                  </button>
                </div>
              )}
            </aside>
          )}
        </main>
  );
}
