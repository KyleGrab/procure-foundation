import { ComingSoonWorkspace } from "@/components/dashboard/ComingSoonWorkspace";
import { TrendingUp } from "lucide-react";

export default function SpendAnalyticsPage() {
  return (
    <ComingSoonWorkspace
      icon={TrendingUp}
      title="Spend Analytics"
      description="A dedicated spend workspace is planned. The underlying data and API (GET /spend-analytics/by-supplier, /trend, /pareto, /abc-classification) already exist and are already used by the Executive Snapshot card and Procurement lens on the canvas."
    />
  );
}
