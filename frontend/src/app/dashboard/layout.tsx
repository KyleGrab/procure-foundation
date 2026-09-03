"use client";

/**
 * Shared shell for every /dashboard/* route - Sidebar + DashboardHeader, rendered once. Was
 * previously duplicated inline across 4 separate places (app/dashboard/page.tsx,
 * app/dashboard/ai-copilot/page.tsx, app/dashboard/opportunities/consolidation-graph/page.tsx,
 * and components/canvas/ProcureIQCanvas.tsx) - confirmed by grep before this was written, not
 * assumed. Mobile drawer state lives here, the one place that actually needs to own it, rather
 * than threaded through four different files or duplicated four times.
 */
import { useState } from "react";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { DashboardHeader } from "@/components/dashboard/DashboardHeader";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-[#0B0D17]">
      <Sidebar isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <DashboardHeader onMenuClick={() => setMobileMenuOpen(true)} />
        {children}
      </div>
    </div>
  );
}
