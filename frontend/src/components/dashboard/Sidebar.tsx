"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, TrendingUp, FileSearch, FileText, Target, Sparkles, Settings, Network, X,
} from "lucide-react";

const NAV_ITEMS = [
  { label: "Overview", href: "/dashboard", icon: LayoutDashboard },
  { label: "Spend Analytics", href: "/dashboard/spend-analytics", icon: TrendingUp },
  { label: "Price Reviews", href: "/price-reviews", icon: FileSearch },
  { label: "Contracts", href: "/dashboard/contracts", icon: FileText },
  { label: "Opportunities", href: "/dashboard/opportunities", icon: Target },
  { label: "Analysis Canvas", href: "/dashboard/canvas", icon: Network },
  { label: "AI Copilot", href: "/dashboard/ai-copilot", icon: Sparkles },
  { label: "Settings", href: "/dashboard/settings", icon: Settings },
];

interface SidebarProps {
  /** Mobile drawer open state - irrelevant on desktop (md:), where the sidebar is always
   * visible regardless of this prop. Optional so every existing call site that doesn't care
   * about mobile behavior keeps working unchanged. */
  isOpen?: boolean;
  onClose?: () => void;
}

export function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const pathname = usePathname();

  return (
    <>
      {/* Mobile-only backdrop - clicking it closes the drawer, same as clicking outside any
          overlay. Doesn't exist on desktop since the sidebar isn't an overlay there. */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex h-screen w-56 flex-col bg-[#0B0D17] border-r border-[#1F2438] transition-transform duration-200 md:static md:translate-x-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between gap-2 px-5 py-6">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-md bg-indigo-500 shadow-[0_0_20px_rgba(99,102,241,0.25)]" />
            <span className="text-slate-100 font-semibold">ProcureIQ</span>
          </div>
          <button onClick={onClose} aria-label="Close menu" className="text-slate-500 hover:text-slate-300 md:hidden">
            <X className="h-4 w-4" />
          </button>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
            const isActive = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                onClick={onClose}
                className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-[#1D2035] text-indigo-400 border-l-2 border-indigo-500"
                    : "text-slate-400 border-l-2 border-transparent hover:text-slate-200 hover:bg-[#131625]"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
