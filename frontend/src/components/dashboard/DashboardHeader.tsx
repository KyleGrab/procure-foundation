"use client";

import { useRouter } from "next/navigation";
import { Bell, LayoutGrid, LogOut, Menu, Search } from "lucide-react";
import { Input } from "@/components/ui/input";

interface DashboardHeaderProps {
  userInitials?: string;
  /** Hamburger trigger, mobile-only (md:hidden on the button itself) - opens the Sidebar drawer
   * whose state lives in app/dashboard/layout.tsx, not here. Optional so this component still
   * renders correctly for any call site that hasn't been updated to pass it. */
  onMenuClick?: () => void;
}

/**
 * Logout: clears the sessionStorage token (same key every API client reads -
 * lib/api.ts/dashboard-api.ts/canvas-api.ts's authHeaders()) and returns to the public root -
 * previously nonexistent anywhere in the app (confirmed by grep before this was written), only
 * a manual sessionStorage.clear() worked.
 *
 * Workspace-picker link: returns to /welcome (the gateway) - ProcureIQCanvas.tsx's own tabs
 * already switch lenses within a workspace; this is for returning to the branded "home" screen
 * itself, which matters more in a white-label context than it would in an unbranded tool.
 */
export function DashboardHeader({ userInitials = "KG", onMenuClick }: DashboardHeaderProps) {
  const router = useRouter();

  function handleLogout() {
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem("procureiq_access_token");
    }
    router.push("/");
  }

  return (
    <header className="flex h-16 items-center justify-between border-b border-[#1F2438] bg-[#0B0D17] px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <button
          onClick={onMenuClick}
          aria-label="Open menu"
          className="text-slate-400 hover:text-slate-200 md:hidden"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="relative w-40 sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <Input placeholder="Search suppliers, SKUs, contracts…" className="w-full pl-9" />
        </div>
      </div>
      <div className="flex items-center gap-4">
        <button
          onClick={() => router.push("/welcome")}
          aria-label="Switch workspace"
          title="Switch workspace"
          className="text-slate-400 hover:text-slate-200"
        >
          <LayoutGrid className="h-4 w-4" />
        </button>
        <button aria-label="Notifications" className="relative text-slate-400 hover:text-slate-200">
          <Bell className="h-5 w-5" />
          <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.6)]" />
        </button>
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1D2035] text-xs font-semibold text-indigo-400 border border-[#1F2438]">
          {userInitials}
        </div>
        <button
          onClick={handleLogout}
          aria-label="Log out"
          title="Log out"
          className="text-slate-400 hover:text-rose-400"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
