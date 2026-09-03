import { ComingSoonWorkspace } from "@/components/dashboard/ComingSoonWorkspace";
import { Settings as SettingsIcon } from "lucide-react";

export default function SettingsPage() {
  return (
    <ComingSoonWorkspace
      icon={SettingsIcon}
      title="Settings"
      description="Organisation settings, user management, and white-label branding configuration are planned. lib/branding.ts already resolves tenant brand config for the gateway - this page would be where an organisation actually edits it, rather than an env var."
    />
  );
}
