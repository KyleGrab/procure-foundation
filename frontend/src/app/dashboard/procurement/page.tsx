/**
 * Procurement Command Centre (PROCUREIQ-PROCUREMENT-COMMAND-CENTRE-R1) - the hub a Procurement
 * Manager lands on between the three-lens gateway and the illustrative Price Review workflow.
 * Lives inside the real dashboard shell (Sidebar + Header, app/dashboard/layout.tsx) like every
 * other procurement tool, reusing the same shared dark background rather than a one-off page
 * with its own chrome - see components/layout/AppBackground.tsx.
 *
 * Every illustrative-only piece here (the banner, the primary CTA, the work queue, and the
 * Supplier Changes card) is gated by the same isDemoModeEnabled guard every other demo entry
 * point uses, and is built entirely from lib/price-review-demo-data.ts's own existing dataset -
 * nothing new is fabricated. Outside demo mode (a real production deployment with no
 * NEXT_PUBLIC_DEMO_MODE flag), none of that renders: this page still works as an honest, purely
 * real hub (heading, Price Reviews/Contracts/Opportunities cards, all linking to real routes),
 * so a demo-mode-only "Open illustrative price review" button is never left dangling as a dead
 * link to a route that would 404 without the flag.
 *
 * A plain server component - no interactivity of its own beyond real <Link> navigation, so no
 * "use client" needed.
 */
import Link from "next/link";
import { ArrowUpRight, FileSearch, FileText, HelpCircle, RefreshCcw, Target, AlertTriangle } from "lucide-react";
import { IllustrativeDemoBanner } from "@/components/price-review-demo/IllustrativeDemoBanner";
import { ProcurementToolCard } from "@/components/dashboard/ProcurementToolCard";
import { isDemoModeEnabled } from "@/lib/demo-mode";
import { DEMO_REVIEW, DEMO_LINES } from "@/lib/price-review-demo-data";
import { classifyLineForInvestigation } from "@/lib/price-review-line-classification";

const needsAttentionCount = DEMO_LINES.filter((line) => classifyLineForInvestigation(line) === "needs_attention").length;
const unknownCount = DEMO_LINES.filter((line) => classifyLineForInvestigation(line) === "unknown").length;

export default function ProcurementCommandCentrePage() {
  const demoEnabled = isDemoModeEnabled(process.env.NODE_ENV, process.env.NEXT_PUBLIC_DEMO_MODE);

  return (
    <main className="flex-1 space-y-6 p-6">
      {demoEnabled && <IllustrativeDemoBanner />}

      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-indigo-300">
          {demoEnabled ? "Illustrative demo workspace" : "Procurement workspace"}
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-100">Procurement</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          A starting point for supplier price reviews, contract oversight, and savings
          opportunities.{" "}
          {demoEnabled
            ? "This workspace shows an illustrative walkthrough end to end - live supplier, contract, and spend data connect here once each source system is wired in."
            : "Live supplier, contract, and spend data connect here once each source system is wired in."}
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        {demoEnabled && (
          <Link
            href="/price-reviews/demo"
            className="inline-flex items-center justify-center gap-1.5 rounded-md bg-indigo-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-300"
          >
            Open illustrative price review
            <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        )}
        <Link
          href="/price-reviews"
          className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[#1F2438] bg-[#131625]/90 px-4 py-2.5 text-sm font-medium text-slate-300 hover:border-indigo-500/40 hover:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          View Price Reviews history
        </Link>
      </div>

      {demoEnabled && (
        <section
          aria-labelledby="procurement-queue-heading"
          className="rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm"
        >
          <h2 id="procurement-queue-heading" className="text-sm font-semibold text-slate-100">
            What needs attention
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Illustrative - from the demo walkthrough&apos;s own dataset, not live supplier data.
          </p>
          <ul className="mt-4 space-y-2">
            <li>
              <Link
                href="/price-reviews/demo"
                className="flex items-start gap-3 rounded-lg border border-[#1F2438] p-3 hover:border-indigo-500/40 hover:bg-[#0B0D17]/40 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
                <span>
                  <span className="block text-sm text-slate-200">
                    {DEMO_REVIEW.supplier_name} submitted a price increase — {DEMO_REVIEW.line_count} lines,
                    effective {DEMO_REVIEW.effective_date}
                  </span>
                  <span className="mt-0.5 block text-xs text-slate-500">
                    Received {DEMO_REVIEW.received_at} · {DEMO_REVIEW.status_label}
                  </span>
                </span>
              </Link>
            </li>
            {needsAttentionCount > 0 && (
              <li>
                <Link
                  href="/price-reviews/demo/analysis"
                  className="flex items-start gap-3 rounded-lg border border-[#1F2438] p-3 hover:border-indigo-500/40 hover:bg-[#0B0D17]/40 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
                  <span className="text-sm text-slate-200">
                    {needsAttentionCount} line{needsAttentionCount === 1 ? "" : "s"}{" "}
                    {needsAttentionCount === 1 ? "needs" : "need"} attention before a decision can be recorded
                  </span>
                </Link>
              </li>
            )}
            {unknownCount > 0 && (
              <li>
                <Link
                  href="/price-reviews/demo/analysis"
                  className="flex items-start gap-3 rounded-lg border border-[#1F2438] p-3 hover:border-indigo-500/40 hover:bg-[#0B0D17]/40 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
                  <span className="text-sm text-slate-200">
                    {unknownCount} line{unknownCount === 1 ? "" : "s"} {unknownCount === 1 ? "has" : "have"} no
                    confirmed match
                  </span>
                </Link>
              </li>
            )}
          </ul>
        </section>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ProcurementToolCard
          icon={FileSearch}
          title="Price Reviews"
          description="Compare supplier price lists, resolve uncertain matches, and record buyer decisions."
          action={{ label: "View Price Reviews", href: "/price-reviews" }}
        />

        {demoEnabled && (
          <ProcurementToolCard
            icon={RefreshCcw}
            title="Supplier Changes"
            description={`${DEMO_REVIEW.supplier_name}'s latest submission, illustrated end to end.`}
            badge="illustrative"
            action={{ label: "Open illustrative walkthrough", href: "/price-reviews/demo" }}
          />
        )}

        <ProcurementToolCard
          icon={FileText}
          title="Contracts"
          description="Contract lifecycle, escalation, and renewal tracking."
          badge="unavailable"
          unavailableReason="Not connected — requires live contract data."
          action={{ label: "Open Contracts workspace", href: "/dashboard/contracts" }}
        />

        <ProcurementToolCard
          icon={Target}
          title="Opportunities"
          description="Savings opportunities and supplier consolidation candidates."
          badge="unavailable"
          unavailableReason="Not connected — requires live spend data."
          action={{ label: "Open Opportunities workspace", href: "/dashboard/opportunities" }}
        />
      </div>
    </main>
  );
}
