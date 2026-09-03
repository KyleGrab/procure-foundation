"use client";

import { Handle, Position, type NodeProps } from "reactflow";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import type { CanvasApiNodeData } from "@/lib/canvas-api";

const STATUS_STYLES: Record<string, { border: string; glow: string; icon: typeof CheckCircle2; iconColor: string }> = {
  positive: {
    border: "border-emerald-500/40", glow: "shadow-[0_0_18px_rgba(52,211,153,0.18)]",
    icon: CheckCircle2, iconColor: "text-emerald-400",
  },
  warning: {
    border: "border-amber-500/40", glow: "shadow-[0_0_18px_rgba(251,191,36,0.18)]",
    icon: AlertTriangle, iconColor: "text-amber-400",
  },
  critical: {
    border: "border-rose-500/40", glow: "shadow-[0_0_18px_rgba(248,113,113,0.22)]",
    icon: XCircle, iconColor: "text-rose-400",
  },
};

function formatMetric(value: string, nodeType: string): string {
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  // Node types whose metric is a count, not a currency figure - shown as a plain integer.
  if (nodeType === "location" || nodeType === "inventory_aging") return num.toFixed(0);
  // DSO/DIO/DPO/CCC are day counts (e.g. "32.4") - formatting these as ZAR currency would show
  // something like "R32", which is actively misleading, not just imprecise. Caught by actually
  // exercising the management lens's real node types for the first time, not assumed correct.
  if (nodeType === "working_capital_metric" || nodeType === "cash_conversion_cycle") {
    return `${num.toFixed(1)} days`;
  }
  return new Intl.NumberFormat("en-ZA", { style: "currency", currency: "ZAR", maximumFractionDigits: 0 }).format(num);
}

/**
 * React Flow custom node - registered as nodeTypes={{ customLensNode: CustomLensNode }} in
 * ProcureIQCanvas.tsx. Reads directly from the backend's CanvasApiNodeData shape, no local
 * recomputation of status or metric value - this component only formats and displays.
 */
export function CustomLensNode({ data }: NodeProps<CanvasApiNodeData>) {
  const style = STATUS_STYLES[data.status] ?? STATUS_STYLES.positive;
  const StatusIcon = style.icon;

  return (
    <div
      className={`min-w-[200px] rounded-xl border ${style.border} ${style.glow} bg-[#131625]/90 p-4 backdrop-blur-md`}
    >
      <Handle type="target" position={Position.Left} className="!bg-indigo-500 !border-none !w-2 !h-2" />
      <Handle type="source" position={Position.Right} className="!bg-indigo-500 !border-none !w-2 !h-2" />

      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-slate-300 leading-tight">{data.label}</p>
        <StatusIcon className={`h-4 w-4 shrink-0 ${style.iconColor}`} />
      </div>

      <p className="mt-2 text-lg font-bold text-slate-100">{formatMetric(data.metricValue, data.nodeType)}</p>

      {data.trend && (
        <p className={`mt-1 text-[11px] ${data.trend.startsWith("-") ? "text-rose-400" : "text-emerald-400"}`}>
          {data.trend}
        </p>
      )}
    </div>
  );
}
