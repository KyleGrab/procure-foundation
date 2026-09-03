import type { LucideIcon } from "lucide-react";
import { Construction } from "lucide-react";

interface ComingSoonWorkspaceProps {
  title: string;
  description: string;
  icon?: LucideIcon;
}

/**
 * Shared placeholder for a linked-but-not-yet-built workspace. One component, not four copies of
 * near-identical markup - the four pages that use this (spend-analytics, contracts,
 * opportunities, settings) are each a few lines rendering this with their own title/description.
 * Exists specifically so a real sidebar link never lands on a raw framework 404 page.
 */
export function ComingSoonWorkspace({ title, description, icon: Icon = Construction }: ComingSoonWorkspaceProps) {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <div className="max-w-md rounded-xl border border-[#1F2438] bg-[#131625]/90 p-8 text-center shadow-lg backdrop-blur-sm">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg bg-[#1D2035] text-indigo-400">
          <Icon className="h-6 w-6" aria-hidden="true" />
        </div>
        <span className="mt-4 inline-block rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-400">
          Coming soon
        </span>
        <h1 className="mt-3 text-lg font-semibold text-slate-100">{title}</h1>
        <p className="mt-2 text-sm text-slate-400">{description}</p>
      </div>
    </main>
  );
}
