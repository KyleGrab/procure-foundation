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

// PROCUREIQ-APP-BACKGROUND-R1: dropped this shell's own opaque bg-[#0B0D17] below - it was
// painting over, rather than showing, the shared app-wide background (same base color, but a
// flat solid div here was hiding AppBackground.tsx's radial glow behind it). Every card in this
// shell already sets its own explicit surface color (bg-[#131625]/90 etc.), so removing this
// outer fill changes nothing about legibility, only lets the same glow the rest of the app now
// has show through here too.
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className="flex min-h-screen">
      <Sidebar isOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <DashboardHeader onMenuClick={() => setMobileMenuOpen(true)} />
        {children}
      </div>
    </div>
  );
}
