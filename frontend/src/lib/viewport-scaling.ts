/**
 * Pure viewport-scaling math - zero imports, no React, no browser APIs. Same §2.1-style
 * separation as treasury-display.ts: the React hook (useWindowDimensions.ts) that actually
 * listens for resize events imports these functions rather than duplicating the math, and is
 * itself untestable in this sandbox (needs `window`, unavailable in plain Node) while this file
 * is genuinely executable (node --test src/lib/viewport-scaling.test.ts).
 */

export type AspectRatioCategory = "ultra-wide" | "wide" | "standard" | "portrait" | "ultra-tall";

/**
 * Threshold boundaries, not arbitrary: 2.5 sits above standard 21:9 ultrawide (2.33) so true
 * super-ultrawide (32:9 = 3.56) gets its own category; 1.4 sits below 16:9 (1.78) so normal
 * widescreen desktops classify as "wide"; 0.8 is the standard/portrait boundary; 0.45 sits just
 * below real 9:16 mobile (0.5625) so phones and vertical tablets land in "portrait", reserving
 * "ultra-tall" for genuinely extreme vertical strips, not ordinary mobile devices.
 */
export function classifyAspectRatio(width: number, height: number): AspectRatioCategory {
  if (width <= 0 || height <= 0) {
    throw new Error(`classifyAspectRatio requires positive width and height, got ${width}x${height}`);
  }
  const ratio = width / height;
  if (ratio >= 2.5) return "ultra-wide";
  if (ratio >= 1.4) return "wide";
  if (ratio >= 0.8) return "standard";
  if (ratio >= 0.45) return "portrait";
  return "ultra-tall";
}

/**
 * Uniform scale factor relative to a base/reference design size - uses the SMALLER of the two
 * axis ratios so neither axis is ever stretched beyond what the other axis's available space
 * allows. This is specifically what prevents squishing/stretching: a naive per-axis scale (width
 * scaled independently of height) would distort aspect ratio the moment the viewport's shape
 * differs from the base design's shape - exactly the failure mode this function exists to avoid.
 *
 * Clamped to [minScale, maxScale] (default 0.5-2.0) - a severely constrained viewport (a small
 * phone against a desktop base) must not shrink text below legibility, and an oversized viewport
 * (an 8K monitor) must not blow components up absurdly large just because the raw ratio says so.
 */
export function calculateProportionalScale(
  currentWidth: number, currentHeight: number, baseWidth: number, baseHeight: number,
  minScale = 0.5, maxScale = 2.0,
): number {
  if (currentWidth <= 0 || currentHeight <= 0 || baseWidth <= 0 || baseHeight <= 0) {
    throw new Error("calculateProportionalScale requires all dimensions to be positive");
  }
  const widthRatio = currentWidth / baseWidth;
  const heightRatio = currentHeight / baseHeight;
  const rawScale = Math.min(widthRatio, heightRatio);
  return Math.min(maxScale, Math.max(minScale, rawScale));
}

/**
 * Standard trailing-edge debounce - collapses a rapid burst of calls (a drag-resize firing
 * dozens of resize events per second) into exactly one call, using the LAST call's arguments,
 * fired only after waitMs of quiet. Generic over the wrapped function's argument tuple rather
 * than typed specifically for resize events, so it's reusable for any other rapid-fire UI event
 * in this codebase without a second, duplicate implementation.
 */
export function debounce<Args extends unknown[]>(
  fn: (...args: Args) => void, waitMs: number,
): (...args: Args) => void {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  return (...args: Args) => {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), waitMs);
  };
}
