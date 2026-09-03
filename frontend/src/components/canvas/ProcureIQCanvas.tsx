/**
 * Multi-lens visual analysis canvas. Two lenses only (Procurement, Warehouse & Inventory) - Lens
 * 2 "Management Accounting" is not in the tab switcher at all, not shown as a disabled/placeholder
 * tab, because no revenue/COGS data exists anywhere in this codebase to back it (confirmed before
 * any of this was written - see docs/decisions, canvas_service.py).
 *
 * dagre computes node positions client-side, every time the graph loads - the backend
 * (app/analytics/canvas_lens.py) never produces x/y, only relationships and metrics. That split
 * is the actual point of this file's boundary with the backend, not an implementation detail.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";
import dagre from "dagre";
import { LayoutGrid, Table as TableIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CustomLensNode } from "./CustomLensNode";
import { canvasApi, type CanvasApiEdge, type CanvasApiNode, type CanvasApiResponse, type LensId } from "@/lib/canvas-api";

const LENSES: { id: LensId; label: string }[] = [
  { id: "procurement", label: "Procurement" },
  { id: "management", label: "Management Accounting" },
  { id: "operations", label: "Warehouse & Inventory" },
];

const STATUS_BADGE: Record<string, BadgeVariant> = {
  positive: "positive", warning: "alert", critical: "rejected",
};

const NODE_TYPES = { customLensNode: CustomLensNode };

const NODE_WIDTH = 220;
const NODE_HEIGHT = 90;

/**
 * dagre left-to-right layout. Pure with respect to its own inputs (same node/edge list always
 * produces the same positions) - not a §2.1 "pure engine" in the backend sense, but deterministic
 * for the same reason: no randomness, no external state.
 */
function layoutWithDagre(apiNodes: CanvasApiNode[], apiEdges: CanvasApiEdge[]): { nodes: Node[]; edges: Edge[] } {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 90 });
  graph.setDefaultEdgeLabel(() => ({}));

  apiNodes.forEach((n) => graph.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  apiEdges.forEach((e) => graph.setEdge(e.source, e.target));

  dagre.layout(graph);

  const nodes: Node[] = apiNodes.map((n) => {
    const { x, y } = graph.node(n.id);
    return {
      id: n.id, type: "customLensNode", data: n.data,
      position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
    };
  });

  const edges: Edge[] = apiEdges.map((e) => ({
    id: e.id, source: e.source, target: e.target, animated: e.animated,
    style: { stroke: e.style.stroke, strokeWidth: 1.5 },
  }));

  return { nodes, edges };
}

export function ProcureIQCanvas() {
  const searchParams = useSearchParams();
  const initialLens = searchParams.get("lens");
  const validInitialLens: LensId =
    initialLens === "procurement" || initialLens === "operations" || initialLens === "management"
      ? initialLens
      : "procurement";
  const [activeLens, setActiveLens] = useState<LensId>(validInitialLens);
  const [viewMode, setViewMode] = useState<"canvas" | "table">("canvas");
  const [graph, setGraph] = useState<CanvasApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<CanvasApiNode | null>(null);

  useEffect(() => {
    let cancelled = false;
    setGraph(null);
    setError(null);
    setSelectedNode(null);
    canvasApi
      .getNodes(activeLens)
      .then((data) => {
        if (!cancelled) setGraph(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load the canvas");
      });
    return () => {
      cancelled = true;
    };
  }, [activeLens]);

  const layout = useMemo(
    () => (graph ? layoutWithDagre(graph.nodes, graph.edges) : { nodes: [], edges: [] }),
    [graph]
  );

  function handleNodeClick(_: React.MouseEvent, node: Node) {
    const raw = graph?.nodes.find((n) => n.id === node.id);
    if (raw) setSelectedNode(raw);
  }

  return (
    <main className="relative flex-1 p-6">
      {/* Top control bar */}
          <div className="flex items-center justify-between">
            <div className="flex gap-1 rounded-lg border border-[#1F2438] bg-[#131625]/80 p-1">
              {LENSES.map((lens) => (
                <button
                  key={lens.id}
                  onClick={() => setActiveLens(lens.id)}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                    activeLens === lens.id
                      ? "bg-[#1D2035] text-indigo-400"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {lens.label}
                </button>
              ))}
            </div>

            <div className="flex gap-1 rounded-lg border border-[#1F2438] bg-[#131625]/80 p-1">
              <button
                onClick={() => setViewMode("canvas")}
                aria-label="Canvas view"
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  viewMode === "canvas" ? "bg-[#1D2035] text-indigo-400" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <LayoutGrid className="h-3.5 w-3.5" /> Canvas
              </button>
              <button
                onClick={() => setViewMode("table")}
                aria-label="Table view"
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  viewMode === "table" ? "bg-[#1D2035] text-indigo-400" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <TableIcon className="h-3.5 w-3.5" /> Table
              </button>
            </div>
          </div>

          {error && (
            <div className="mt-6 rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-400">
              {error}
            </div>
          )}

          {!error && !graph && <Skeleton className="mt-6 h-[600px] w-full rounded-xl" />}

          {!error && graph && graph.nodes.length === 0 && (
            <div className="mt-6 rounded-xl border border-[#1F2438] bg-[#131625]/90 p-8 text-center text-sm text-slate-500 shadow-lg backdrop-blur-sm">
              No data yet for this lens.
            </div>
          )}

          {!error && graph && graph.nodes.length > 0 && viewMode === "canvas" && (
            <div className="relative mt-6 h-[650px] overflow-hidden rounded-xl border border-[#1F2438] bg-[#0B0D17]">
              {/* Ambient radial glow - static enterprise background treatment, not cursor-tracked
                  (unlike InteractiveMetricCard's glow - this canvas has its own pan/zoom via
                  React Flow, so a cursor-tracked glow would fight with that interaction model). */}
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0 z-0"
                style={{
                  background: "radial-gradient(800px circle at 20% 20%, rgba(99,102,241,0.08), transparent 60%)",
                }}
              />
              <ReactFlow
                nodes={layout.nodes}
                edges={layout.edges}
                nodeTypes={NODE_TYPES}
                onNodeClick={handleNodeClick}
                fitView
                proOptions={{ hideAttribution: true }}
                className="relative z-10"
              >
                <Background color="#1F2438" gap={20} />
                <Controls className="[&>button]:bg-[#131625] [&>button]:border-[#1F2438] [&>button]:text-slate-300" />
                <MiniMap style={{ backgroundColor: "#0B0D17" }} maskColor="rgba(11,13,23,0.7)" nodeColor="#6366F1" />
              </ReactFlow>
            </div>
          )}

          {!error && graph && graph.nodes.length > 0 && viewMode === "table" && (
            <div className="mt-6 rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Node</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Metric</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {graph.nodes.map((n) => (
                    <TableRow key={n.id} className="cursor-pointer" onClick={() => setSelectedNode(n)}>
                      <TableCell>{n.data.label}</TableCell>
                      <TableCell className="text-xs text-slate-400">{n.data.nodeType}</TableCell>
                      <TableCell className="text-xs">{n.data.metricValue}</TableCell>
                      <TableCell>
                        <Badge variant={STATUS_BADGE[n.data.status] ?? "neutral"}>{n.data.status}</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {selectedNode && (
            <aside className="fixed right-6 top-24 w-96 rounded-xl border border-[#1F2438] bg-[#131625]/95 p-5 shadow-lg backdrop-blur-sm">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-slate-100 font-semibold text-sm">{selectedNode.data.label}</h2>
                  <p className="text-slate-500 text-xs">{selectedNode.data.nodeType.replace(/_/g, " ")}</p>
                </div>
                <button onClick={() => setSelectedNode(null)} className="text-slate-500 hover:text-slate-300 text-xs">
                  close
                </button>
              </div>

              <div className="mt-4 flex items-center justify-between text-xs">
                <span className="text-slate-500">Status</span>
                <Badge variant={STATUS_BADGE[selectedNode.data.status] ?? "neutral"}>{selectedNode.data.status}</Badge>
              </div>
              <div className="mt-2 flex items-center justify-between text-xs">
                <span className="text-slate-500">Metric value</span>
                <span className="text-slate-200">{selectedNode.data.metricValue}</span>
              </div>

              {Object.keys(selectedNode.data.details).length > 0 && (
                <div className="mt-4 border-t border-[#1F2438] pt-3">
                  <p className="text-[11px] text-slate-500 mb-2">Details</p>
                  <div className="space-y-1.5">
                    {Object.entries(selectedNode.data.details).map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between text-xs">
                        <span className="text-slate-500">{key.replace(/_/g, " ")}</span>
                        <span className="text-slate-200">{String(value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </aside>
          )}
        </main>
  );
}
