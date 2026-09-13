/**
 * One tool card on the Procurement Command Centre (app/dashboard/procurement/page.tsx).
 * Deliberately generic (no hardcoded "Price Reviews"/"Contracts" knowledge here) so the same
 * component serves both a fully real, working card and an honest "not connected" one - the
 * distinction is entirely in what its caller passes, not a special case inside this file.
 *
 * Every card always has a working `action` link - there is no variant that renders a button with
 * no destination. An unavailable tool still links somewhere real (its own honest "coming soon"
 * page, e.g. /dashboard/contracts) rather than being a dead end; `unavailableReason` is shown
 * as the stated reason alongside that link, never a fabricated number pretending the tool works.
 */
import Link from "next/link";
import { ArrowUpRight, type LucideIcon } from "lucide-react";

export type ProcurementToolCardBadge = "illustrative" | "unavailable";

const BADGE_LABEL: Record<ProcurementToolCardBadge, string> = {
  illustrative: "Illustrative",
  unavailable: "Data required",
};

const BADGE_CLASSES: Record<ProcurementToolCardBadge, string> = {
  illustrative: "border-indigo-500/20 bg-indigo-500/10 text-indigo-300",
  unavailable: "border-slate-600/40 bg-slate-500/10 text-slate-400",
};

interface ProcurementToolCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action: { label: string; href: string };
  badge?: ProcurementToolCardBadge;
  /** Shown as an explicit, honest reason when the tool itself isn't connected to live data yet -
   * never omitted silently in favour of a fabricated number or status. */
  unavailableReason?: string;
}

export function ProcurementToolCard({
  icon: Icon,
  title,
  description,
  action,
  badge,
  unavailableReason,
}: ProcurementToolCardProps) {
  return (
    <div className="flex flex-col rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
      <div className="flex items-start justify-between gap-2">
        <Icon className="h-5 w-5 text-indigo-400" aria-hidden="true" />
        {badge && (
          <span
            className={`rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${BADGE_CLASSES[badge]}`}
          >
            {BADGE_LABEL[badge]}
          </span>
        )}
      </div>
      <h3 className="mt-3 text-sm font-semibold text-slate-100">{title}</h3>
      <p className="mt-1 flex-1 text-xs leading-relaxed text-slate-400">{description}</p>
      {unavailableReason && (
        <p className="mt-2 text-xs text-amber-400" role="status">
          {unavailableReason}
        </p>
      )}
      <Link
        href={action.href}
        className="mt-4 inline-flex items-center gap-1 self-start rounded text-xs font-medium text-indigo-400 hover:text-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
      >
        {action.label}
        <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
      </Link>
    </div>
  );
}
