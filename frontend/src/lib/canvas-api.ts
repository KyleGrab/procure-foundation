/**
 * Typed client for GET /canvas/nodes (backend/app/api/v1/canvas.py). Two lenses only -
 * 'procurement' and 'operations'. 'accounting' (Lens 2) is intentionally not a valid value here:
 * no revenue/COGS data exists anywhere in this codebase, so there is no third lens to request.
 * No `position` field on CanvasApiNode - the backend never computes coordinates (same §2.1
 * boundary as domain_graph.py's graph); ProcureIQCanvas.tsx's dagre layout owns that entirely.
 */
import { apiFetch } from "./api";

export type LensId = "procurement" | "operations" | "management";

export type NodeStatus = "positive" | "warning" | "critical";

export interface CanvasApiNodeData {
  label: string;
  nodeType: string;
  metricValue: string;
  status: NodeStatus;
  trend: string | null;
  details: Record<string, unknown>;
}

export interface CanvasApiNode {
  id: string;
  type: "customLensNode";
  data: CanvasApiNodeData;
}

export interface CanvasApiEdge {
  id: string;
  source: string;
  target: string;
  animated: boolean;
  style: { stroke: string };
}

export interface CanvasApiResponse {
  nodes: CanvasApiNode[];
  edges: CanvasApiEdge[];
}

function authHeaders(): { accessToken?: string } {
  const token = typeof window !== "undefined" ? sessionStorage.getItem("procureiq_access_token") : null;
  return token ? { accessToken: token } : {};
}

export const canvasApi = {
  getNodes: (lens: LensId) => apiFetch<CanvasApiResponse>(`/canvas/nodes?lens=${lens}`, authHeaders()),
};
