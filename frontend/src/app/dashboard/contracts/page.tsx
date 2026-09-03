import { ComingSoonWorkspace } from "@/components/dashboard/ComingSoonWorkspace";
import { FileText } from "lucide-react";

export default function ContractsPage() {
  return (
    <ComingSoonWorkspace
      icon={FileText}
      title="Contracts"
      description="A dedicated contract list and detail workspace is planned. The backend (contract lifecycle, escalation calculations, renewal alerts) has been built and tested since Phase 3 - this page is the missing frontend for it."
    />
  );
}
