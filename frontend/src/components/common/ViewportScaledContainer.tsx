/**
 * Wraps content in a container that scales proportionally with the viewport, using
 * useWindowDimensions' already-tested scale factor (viewport-scaling.ts,
 * calculateProportionalScale - uniform scaling via the constraining axis, never per-axis
 * stretching). Not executed in this sandbox (needs a real browser/jsdom, same standing
 * limitation as every component this engagement).
 *
 * The scale factor is exposed as a CSS custom property (--viewport-scale) rather than applied
 * via a wholesale `transform: scale(...)` on the container - a transform-scale would visually
 * shrink/grow the container's rendered pixels without changing layout flow (text could overflow
 * its own scaled box, click targets would be misaligned with their visual position). Using the
 * custom property lets descendant elements opt in via `font-size: calc(1rem * var(--viewport-scale))`
 * or similar, which scales real layout, not just a visual transform.
 */
"use client";

import { useWindowDimensions } from "@/lib/useWindowDimensions";

export interface ViewportScaledContainerProps {
  children: React.ReactNode;
  className?: string;
}

export function ViewportScaledContainer({ children, className = "" }: ViewportScaledContainerProps) {
  const { scale, category } = useWindowDimensions();

  return (
    <div
      className={`w-full ${className}`}
      style={{ "--viewport-scale": scale } as React.CSSProperties}
      data-aspect-category={category}
    >
      {children}
    </div>
  );
}
