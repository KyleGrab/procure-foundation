/**
 * Post-login white-label gateway - the workspace picker between authentication and the real
 * dashboard. Uses the app's actual dark tokens (bg-[#0B0D17]/bg-[#131625]/border-[#1F2438]/
 * indigo-500), not a separate palette invented for this screen - "match the dark aesthetic" per
 * this feature's rule means match what's real, not introduce a fourth color language on top of
 * the two the app already has (the main dashboard's indigo, the consolidation graph's status
 * colors).
 *
 * Each card deep-links to /dashboard/canvas?lens=X - ProcureIQCanvas.tsx reads that param on
 * mount, so this isn't a dead link into a canvas that ignores it.
 *
 * The worker character is real now (public/images/pps-logistics-worker-front-removebg-preview.png,
 * genuine 447x558px, confirmed) - placed once, in the hero, not turned into the head-tracking
 * mascot from the earlier fabricated draft. That behavior was never actually built and isn't
 * being added now just because a real image exists to put it on; a static, well-composed
 * placement is the honest scope of what this turn asked for ("wire in the actual assets"), not
 * license to add motion behavior nobody requested.
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { motion } from "framer-motion";
import { ArrowUpRight, Calculator, ShoppingCart, Truck, type LucideIcon } from "lucide-react";
import { TruckTransition } from "./TruckTransition";
import { DEFAULT_CLIENT_BRAND, type ClientBrand } from "@/types/client-brand";

interface GatewayLens {
  id: "procurement" | "management" | "operations";
  title: string;
  description: string;
  href: string;
  icon: LucideIcon;
  accent: string;
}

const LENSES: readonly GatewayLens[] = [
  {
    id: "procurement", title: "Procurement Analysis",
    description: "Supplier spend, rebate leakage, and contract renewals.",
    href: "/dashboard/canvas?lens=procurement", icon: ShoppingCart, accent: "text-indigo-400",
  },
  {
    id: "management", title: "Management Accounting",
    description: "Cost-to-serve, working capital, and cash conversion cycle.",
    href: "/dashboard/canvas?lens=management", icon: Calculator, accent: "text-emerald-400",
  },
  {
    id: "operations", title: "Operations & Inventory",
    description: "Warehouse aging, stock movement, and expiry risk.",
    href: "/dashboard/canvas?lens=operations", icon: Truck, accent: "text-amber-400",
  },
];

interface HomeGatewayProps {
  clientBrand?: ClientBrand;
}

export function HomeGateway({ clientBrand = DEFAULT_CLIENT_BRAND }: HomeGatewayProps) {
  const router = useRouter();
  const [transitioning, setTransitioning] = useState<string | null>(null);
  const [workerImageFailed, setWorkerImageFailed] = useState(false);

  function handleSelect(lens: GatewayLens) {
    // Truck transition only for Operations, per this feature's rule ("Operations card launches
    // the truck animation") - the other two cards navigate immediately, no reason to gate every
    // lens behind the same flourish.
    if (lens.id === "operations") {
      setTransitioning(lens.href);
      return;
    }
    router.push(lens.href);
  }

  const showWorker = Boolean(clientBrand.workerImageSrc) && !workerImageFailed;

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#0B0D17] px-6 py-16">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ background: "radial-gradient(600px circle at 50% 30%, rgba(99,102,241,0.10), transparent 60%)" }}
      />

      {/* Worker character - real asset, 0.8:1 (447x558px, confirmed) box matching its actual
          aspect ratio. Positioned to one side of the header so it doesn't compete with the
          brand mark or the three lens cards below - decorative, aria-hidden, not the only way
          to understand the page. */}
      {showWorker && (
        <div
          aria-hidden
          className="pointer-events-none absolute bottom-0 right-[4%] hidden h-[420px] w-[336px] sm:block lg:h-[520px] lg:w-[416px]"
        >
          <Image
            src={clientBrand.workerImageSrc as string}
            alt=""
            fill
            sizes="(max-width: 1023px) 336px, 416px"
            className="object-contain object-bottom drop-shadow-[0_24px_28px_rgba(0,0,0,0.5)]"
            onError={() => setWorkerImageFailed(true)}
            priority
          />
        </div>
      )}

      <header className="relative z-10 mb-12 text-center">
        {clientBrand.logoUrl ? (
          <Image
            src={clientBrand.logoUrl} alt={clientBrand.logoAlt ?? `${clientBrand.name} logo`}
            width={48} height={48} className="mx-auto mb-4 rounded-lg object-contain"
          />
        ) : (
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg text-sm font-bold text-white"
            style={{ backgroundColor: clientBrand.primaryColor }}
          >
            {clientBrand.name.slice(0, 2).toUpperCase()}
          </div>
        )}
        <p className="text-xs font-medium tracking-[0.2em] text-slate-500">{clientBrand.name.toUpperCase()}</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-100">Choose your workspace</h1>
        <p className="mt-1 text-sm text-slate-400">Powered by ProcureIQ</p>
      </header>

      <div className="relative z-10 grid w-full max-w-4xl gap-4 sm:grid-cols-3">
        {LENSES.map((lens) => {
          const Icon = lens.icon;
          return (
            <motion.button
              key={lens.id}
              onClick={() => handleSelect(lens)}
              whileHover={{ y: -4 }}
              transition={{ type: "spring", stiffness: 260, damping: 22 }}
              className="group flex flex-col rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 text-left shadow-lg backdrop-blur-sm transition-colors hover:border-indigo-500/40"
            >
              <div className="flex items-start justify-between">
                <Icon className={`h-6 w-6 ${lens.accent}`} aria-hidden="true" />
                <ArrowUpRight className="h-4 w-4 text-slate-600 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-indigo-400" />
              </div>
              <h2 className="mt-4 text-sm font-semibold text-slate-100">{lens.title}</h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-400">{lens.description}</p>
            </motion.button>
          );
        })}
      </div>

      <TruckTransition
        active={transitioning !== null}
        clientBrand={clientBrand}
        onComplete={() => {
          if (transitioning) router.push(transitioning);
        }}
      />
    </div>
  );
}
