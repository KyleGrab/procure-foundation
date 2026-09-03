/**
 * Real dashboard, built in Phase 5 (originally slated for Phase 8 per the comment this replaces -
 * moved up because Phase 5's spend-analytics/opportunities backend gave it real data to show).
 * Renders MetricRibbon + the 70/30 and 60/40 split sections per the dark-mode visual spec -
 * Sidebar/DashboardHeader now live once in app/dashboard/layout.tsx, not duplicated here.
 * Every widget fetches from the real, built (never-run-in-this-sandbox) Phase 5 backend routes -
 * no mocked data anywhere in this page or its children.
 */
import { InteractiveMetricCard } from "@/components/ui/InteractiveMetricCard";
import { MetricRibbon } from "@/components/dashboard/MetricRibbon";
import { SpendTrendChart } from "@/components/dashboard/SpendTrendChart";
import { TopSupplierIncreases } from "@/components/dashboard/TopSupplierIncreases";
import { AuditActivityTable } from "@/components/dashboard/AuditActivityTable";
import { SpendBreakdownDonut } from "@/components/dashboard/SpendBreakdownDonut";

export default function DashboardPage() {
  return (
    <main className="flex-1 space-y-6 p-6">
      <MetricRibbon />
      <InteractiveMetricCard />

      <div className="grid grid-cols-10 gap-6">
        <div className="col-span-7">
          <SpendTrendChart />
        </div>
        <div className="col-span-3">
          <TopSupplierIncreases />
        </div>
      </div>

      <div className="grid grid-cols-10 gap-6">
        <div className="col-span-6">
          <AuditActivityTable />
        </div>
        <div className="col-span-4">
          <SpendBreakdownDonut />
        </div>
      </div>
    </main>
  );
}
