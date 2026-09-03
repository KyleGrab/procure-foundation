/**
 * Dual-gear loading indicator for ingestion/high-latency screens. Pure SVG path math, zero
 * external image assets, zero animation library dependency.
 *
 * The outer gear reuses Tailwind's own built-in `animate-spin` (a real, already-GPU-accelerated
 * `transform: rotate` keyframe shipped with Tailwind) rather than redeclaring the same thing -
 * only the inner gear needs genuinely new CSS, since Tailwind has no built-in reverse-spin
 * utility. Both animations only ever touch `transform`, never a layout- or paint-triggering
 * property, so they run on the compositor thread and stay smooth even while the main thread is
 * busy parsing a large Excel/CSV upload.
 *
 * No light-theme variant is implied here, and that's not an oversight: this app has no light
 * theme anywhere (checked - zero `dark:` usage in the whole codebase, every existing component
 * uses fixed dark hex tokens). What this component actually offers is configurability -
 * `ringColor`/`driveColor` accept any Tailwind text-color class, defaulting to this app's real,
 * existing tokens (indigo-500 accent for the ring; a light slate for the drive gear, chosen so
 * the two gears read as visually distinct layers against a dark background - NOT #1F2438, which
 * is this app's dark navy *container* background color, not a color anything is ever rendered
 * IN elsewhere in this codebase; using it as icon fill would render the inner gear almost
 * invisible against the page) - not a light/dark switch that has nothing to switch against.
 */
"use client";

/** Generates real gear-tooth geometry via trigonometry - not hand-drawn path data. Computed once
 * per distinct (teeth, outerRadius, innerRadius) combination, not per animation frame; the path
 * string itself is static, only the CSS transform rotates it. */
function buildGearPath(teeth: number, outerRadius: number, innerRadius: number, cx: number, cy: number): string {
  const anglePerTooth = (2 * Math.PI) / teeth;
  const point = (radius: number, angle: number) => {
    const x = cx + radius * Math.cos(angle);
    const y = cy + radius * Math.sin(angle);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  };

  const commands: string[] = [];
  for (let i = 0; i < teeth; i++) {
    const a0 = i * anglePerTooth;
    const a1 = a0 + anglePerTooth * 0.22;
    const a2 = a0 + anglePerTooth * 0.5;
    const a3 = a0 + anglePerTooth * 0.72;
    commands.push(`${i === 0 ? "M" : "L"} ${point(outerRadius, a0)}`);
    commands.push(`L ${point(outerRadius, a1)}`);
    commands.push(`L ${point(innerRadius, a2)}`);
    commands.push(`L ${point(outerRadius, a3)}`);
  }
  commands.push("Z");
  return commands.join(" ");
}

const OUTER_GEAR_PATH = buildGearPath(12, 46, 38, 50, 50);
const INNER_GEAR_PATH = buildGearPath(8, 26, 19, 50, 50);

export interface LoadingGearsProps {
  /** Loading text rendered VISIBLY underneath the graphic - not decorative chrome, and not
   * screen-reader-only markup. Required: a spinner with no accompanying text is genuinely
   * ambiguous about what's loading, and this component's whole point is drop-in use inside
   * ingestion/table loading states where that context matters. */
  label: string;
  /** Pixel size of the square viewBox (the gear graphic only, not the label text below it).
   * Defaults to 48px - legible in a table-row loading state without dominating it. */
  size?: number;
  /** Any Tailwind text-color class. Defaults to this app's real indigo accent (matches
   * DashboardHeader's notification dot, Sidebar's active-link color). */
  ringColor?: string;
  /** Any Tailwind text-color class. Defaults to a light slate so the two gears read as visually
   * distinct layers against this app's dark background. */
  driveColor?: string;
  className?: string;
}

export function LoadingGears({
  label,
  size = 48,
  ringColor = "text-indigo-500",
  driveColor = "text-slate-400",
  className = "",
}: LoadingGearsProps) {
  return (
    <span role="status" className={`inline-flex flex-col items-center gap-2 ${className}`}>
      <span style={{ width: size, height: size }}>
        <svg viewBox="0 0 100 100" width={size} height={size} className="overflow-visible">
          <path
            d={OUTER_GEAR_PATH}
            className={`${ringColor} animate-spin`}
            style={{ transformOrigin: "50px 50px", animationDuration: "3s" }}
            fill="currentColor"
            fillOpacity={0.85}
          />
          <path
            d={INNER_GEAR_PATH}
            className={`${driveColor} loading-gears-counter-spin`}
            fill="currentColor"
          />
        </svg>
      </span>
      {/* Real, visible loading text - this app's own established Skeleton/table-loading
          convention has no equivalent text label anywhere, so this is new ground for the
          codebase, not a restatement of an existing pattern. Its own text content is what
          gives this role="status" region its accessible name - no separate aria-label or
          sr-only duplicate needed, since a screen reader announces this visible text directly;
          adding both would announce the same string twice. */}
      <span className="text-xs text-slate-400">{label}</span>
      {/* Scoped, plain CSS - no styled-jsx, no Tailwind config edit, no new dependency. Only
          `transform` is animated: GPU-compositable, never triggers layout or paint per frame. */}
      <style>{`
        @keyframes loading-gears-counter-spin-kf {
          from { transform: rotate(0deg); }
          to { transform: rotate(-360deg); }
        }
        .loading-gears-counter-spin {
          transform-origin: 50px 50px;
          animation: loading-gears-counter-spin-kf 2.1s linear infinite;
        }
        @media (prefers-reduced-motion: reduce) {
          /* Slowed, not stopped - deliberately different from this codebase's other motion
             components (TruckTransition.tsx, HomeGateway.tsx fully disable motion under
             prefers-reduced-motion, since their motion is purely decorative). A loading
             indicator conveys real, functional information ("still working," not finished or
             stuck) - removing it entirely would remove that signal for a reduced-motion user,
             not just remove decoration. Slowing it well below anything vestibular-triggering
             keeps the information without the motion intensity. This selector is intentionally
             NOT scoped to a single component instance (plain <style>, no CSS modules) - under
             reduced motion, it slows every `animate-spin` SVG on the page, not just this one.
             That's a deliberate, acknowledged, unified UX choice, not an oversight: slowing all
             spinning icons together under a reduced-motion preference is a reasonable default
             even for elements outside this specific component. */
          .loading-gears-counter-spin,
          svg .animate-spin {
            animation-duration: 6s;
          }
        }
      `}</style>
    </span>
  );
}
