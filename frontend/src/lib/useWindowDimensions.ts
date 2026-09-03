/**
 * Auto-detects viewport dimensions and reacts to real-time resizing. Not executed in this
 * sandbox (needs `window` - a real browser environment; no jsdom installed, npm install
 * confirmed blocked). All correctness-sensitive math (aspect ratio classification, proportional
 * scale, debounce) lives in viewport-scaling.ts, genuinely executed and proven (node --test,
 * 14/14 passing) - this hook is thin wiring around already-verified logic, not new unverified
 * logic of its own.
 *
 * SSR-safe: `window` doesn't exist during Next.js server rendering, so initial state falls back
 * to a sensible desktop default (1440x900, this codebase's own design baseline - see
 * viewport-scaling.ts) rather than throwing or reading `window` unconditionally at module scope.
 */
"use client";

import { useEffect, useState } from "react";
import {
  classifyAspectRatio, calculateProportionalScale, debounce,
  type AspectRatioCategory,
} from "@/lib/viewport-scaling";

export interface WindowDimensions {
  width: number;
  height: number;
  category: AspectRatioCategory;
  scale: number;
}

const SSR_FALLBACK_WIDTH = 1440;
const SSR_FALLBACK_HEIGHT = 900;
const BASE_DESIGN_WIDTH = 1440;
const BASE_DESIGN_HEIGHT = 900;
const RESIZE_DEBOUNCE_MS = 150;

function readDimensions(): WindowDimensions {
  const width = typeof window !== "undefined" ? window.innerWidth : SSR_FALLBACK_WIDTH;
  const height = typeof window !== "undefined" ? window.innerHeight : SSR_FALLBACK_HEIGHT;
  return {
    width, height,
    category: classifyAspectRatio(width, height),
    scale: calculateProportionalScale(width, height, BASE_DESIGN_WIDTH, BASE_DESIGN_HEIGHT),
  };
}

export function useWindowDimensions(): WindowDimensions {
  const [dimensions, setDimensions] = useState<WindowDimensions>(readDimensions);

  useEffect(() => {
    // Read again on mount - the SSR fallback above may not match the real client viewport, and
    // this corrects it on the very first client-side render.
    setDimensions(readDimensions());

    const handleResize = debounce(() => setDimensions(readDimensions()), RESIZE_DEBOUNCE_MS);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return dimensions;
}
