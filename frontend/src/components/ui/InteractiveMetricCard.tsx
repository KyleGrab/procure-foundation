/**
 * Interactive executive metrics card - real Framer Motion spring-based tilt, wired to real data
 * from GET /dashboard/executive-metrics (backend/app/api/v1/dashboard.py), not a mocked route.
 *
 * Deliberately three metrics, not the four/"risk score" originally proposed: Active Contracts,
 * Open Rebate Periods, and Consolidation Flags are all real, queryable counts. "Supplier Risk
 * Score" was dropped rather than invented - nothing in this codebase computes supplier risk as a
 * concept (confirmed by grep before writing this file), and putting a fabricated number next to
 * three real ones would be worse than a card with three metrics instead of four.
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion";
import { FileText, TrendingUp, Users } from "lucide-react";
import { Skeleton } from "./skeleton";
import { dashboardApi, type ExecutiveMetrics } from "@/lib/dashboard-api";

const TILT_RANGE_DEG = 10;
const SPRING_CONFIG = { stiffness: 200, damping: 22, mass: 0.5 };

function useIsTouchDevice(): boolean {
  const [isTouch, setIsTouch] = useState(false);
  useEffect(() => {
    setIsTouch(
      typeof window !== "undefined" &&
        ("ontouchstart" in window || navigator.maxTouchPoints > 0)
    );
  }, []);
  return isTouch;
}

export function InteractiveMetricCard() {
  const cardRef = useRef<HTMLDivElement>(null);
  const isTouchDevice = useIsTouchDevice();
  const prefersReducedMotion = useReducedMotion();
  const tiltDisabled = isTouchDevice || Boolean(prefersReducedMotion);

  const [metrics, setMetrics] = useState<ExecutiveMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  // -0.5..0.5 normalized cursor position within the card, driving both the spring-based tilt and
  // the ambient glow's CSS custom properties (set directly on the element, not left as decorative
  // dead code that never actually tracks the cursor).
  const pointerX = useMotionValue(0);
  const pointerY = useMotionValue(0);
  const rotateX = useSpring(useTransform(pointerY, [-0.5, 0.5], [TILT_RANGE_DEG, -TILT_RANGE_DEG]), SPRING_CONFIG);
  const rotateY = useSpring(useTransform(pointerX, [-0.5, 0.5], [-TILT_RANGE_DEG, TILT_RANGE_DEG]), SPRING_CONFIG);

  useEffect(() => {
    let cancelled = false;
    dashboardApi
      .executiveMetrics()
      .then((data) => {
        if (!cancelled) setMetrics(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load executive metrics");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    if (tiltDisabled || !cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const relativeX = e.clientX - rect.left;
    const relativeY = e.clientY - rect.top;
    pointerX.set(relativeX / rect.width - 0.5);
    pointerY.set(relativeY / rect.height - 0.5);
    cardRef.current.style.setProperty("--glow-x", `${relativeX}px`);
    cardRef.current.style.setProperty("--glow-y", `${relativeY}px`);
  }

  function handleMouseLeave() {
    // Springs handle the smooth decay back to neutral on their own once the target is 0 - no
    // manual animation needed here, that's the entire point of useSpring over a raw useState.
    pointerX.set(0);
    pointerY.set(0);
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-6 text-sm text-rose-400">
        {error}
      </div>
    );
  }

  if (!metrics) {
    return <Skeleton className="h-56 w-full rounded-2xl" />;
  }

  const items = [
    { label: "Active Contracts", value: metrics.active_contracts, icon: FileText, tone: "text-indigo-400" },
    { label: "Open Rebate Periods", value: metrics.open_rebate_periods, icon: TrendingUp, tone: "text-emerald-400" },
    { label: "Consolidation Flags", value: metrics.open_consolidation_flags, icon: Users, tone: "text-amber-400" },
  ];

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{ perspective: 1200 }}
      className="group relative"
    >
      <motion.div
        style={{
          rotateX: tiltDisabled ? 0 : rotateX,
          rotateY: tiltDisabled ? 0 : rotateY,
          transformStyle: "preserve-3d",
        }}
        className="relative overflow-hidden rounded-2xl border border-[#1F2438] bg-[#131625]/80 p-6 shadow-lg backdrop-blur-md"
      >
        {/* Ambient glow - tracks the cursor via --glow-x/--glow-y set in handleMouseMove above,
            not a static decoration. Only visible on hover (group-hover), and only meaningful when
            tilt itself is active. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          style={{
            background:
              "radial-gradient(360px circle at var(--glow-x, 50%) var(--glow-y, 50%), rgba(99,102,241,0.18), transparent 65%)",
          }}
        />

        <div style={{ transform: "translateZ(30px)", transformStyle: "preserve-3d" }}>
          <h3 className="text-slate-100 font-semibold text-sm">Executive Snapshot</h3>
          <p className="mt-1 text-xs text-slate-500">Live procurement metrics</p>

          <div className="mt-5 grid grid-cols-3 gap-3">
            {items.map(({ label, value, icon: Icon, tone }) => (
              <div
                key={label}
                style={{ transform: "translateZ(16px)" }}
                className="rounded-xl border border-[#1F2438] bg-[#0B0D17]/70 p-3"
              >
                <Icon className={`h-4 w-4 ${tone}`} />
                <p className="mt-2 text-xl font-bold text-slate-100">{value}</p>
                <p className="mt-0.5 text-[10px] leading-tight text-slate-500">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
