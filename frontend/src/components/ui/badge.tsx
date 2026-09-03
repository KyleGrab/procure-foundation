import type { ReactNode } from "react";

export type BadgeVariant = "positive" | "alert" | "neutral" | "pending" | "verified" | "rejected";

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  // Exact classes from the visual spec - positive/alert are the two named in the spec directly;
  // neutral/pending/verified/rejected extend the same token language for the audit-activity
  // table's status badges, which the spec names but doesn't give exact classes for.
  positive: "text-emerald-400 bg-emerald-500/10 border border-emerald-500/20",
  alert: "text-amber-400 bg-amber-500/10 border border-amber-500/20",
  neutral: "text-slate-400 bg-slate-500/10 border border-slate-500/20",
  pending: "text-amber-400 bg-amber-500/10 border border-amber-500/20",
  verified: "text-emerald-400 bg-emerald-500/10 border border-emerald-500/20",
  rejected: "text-rose-400 bg-rose-500/10 border border-rose-500/20",
};

export function Badge({ variant = "neutral", children }: { variant?: BadgeVariant; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${VARIANT_CLASSES[variant]}`}>
      {children}
    </span>
  );
}
