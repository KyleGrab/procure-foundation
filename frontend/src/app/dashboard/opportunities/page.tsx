import { ComingSoonWorkspace } from "@/components/dashboard/ComingSoonWorkspace";
import { Target } from "lucide-react";

export default function OpportunitiesPage() {
  return (
    <ComingSoonWorkspace
      icon={Target}
      title="Opportunities"
      description="A full opportunity register list view is planned - closer to real than the other placeholders on this nav: GET /opportunities, the savings-type waterfall, and opportunitiesApi are all already built and working (see the Supplier Consolidation Graph for one real, working view over this same data)."
    />
  );
}
