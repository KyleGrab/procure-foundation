/**
 * Genuinely executable tests for the pure, non-React viewport math in viewport-scaling.ts - run
 * via `node --test src/lib/viewport-scaling.test.ts` (Node 22 native TS + built-in mock timers
 * for the debounce tests, no external framework). The React hook itself (useWindowDimensions.ts,
 * which needs `window`/resize events - browser-only, unavailable in plain Node) is written but
 * not executed, same honest split as treasury-display.ts/treasury-api.ts in Phase 1.
 *
 * Stress-case dimensions used below are real device/monitor specs, not arbitrary numbers:
 * 32:9 ultra-wide (Samsung Odyssey G9-class, 5120x1440), 9:16 mobile (iPhone-class, 390x844),
 * iPad portrait (820x1180), and a deliberately extreme 100x2000 vertical strip to prove the
 * classifier doesn't just handle "normal" portrait but genuinely extreme cases too.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyAspectRatio, calculateProportionalScale, debounce } from "./viewport-scaling.ts";

test("32:9 ultra-wide monitor classifies as ultra-wide", () => {
  assert.strictEqual(classifyAspectRatio(5120, 1440), "ultra-wide"); // ratio = 3.556
});

test("standard 16:9 desktop classifies as wide", () => {
  assert.strictEqual(classifyAspectRatio(1920, 1080), "wide"); // ratio = 1.778
});

test("9:16 mobile portrait classifies as portrait, not ultra-tall", () => {
  assert.strictEqual(classifyAspectRatio(390, 844), "portrait"); // ratio = 0.462
});

test("iPad portrait classifies as portrait", () => {
  assert.strictEqual(classifyAspectRatio(820, 1180), "portrait"); // ratio = 0.695
});

test("an extreme vertical strip classifies as ultra-tall, distinct from normal portrait", () => {
  assert.strictEqual(classifyAspectRatio(100, 2000), "ultra-tall"); // ratio = 0.05
});

test("zero or negative width/height is refused, never silently misclassified", () => {
  assert.throws(() => classifyAspectRatio(0, 1000));
  assert.throws(() => classifyAspectRatio(1000, -1));
});

test("proportional scale at exactly the base dimensions is 1.0 (no scaling)", () => {
  const scale = calculateProportionalScale(1440, 900, 1440, 900);
  assert.strictEqual(scale, 1.0);
});

test("scale uses the SMALLER axis ratio - proves uniform scaling, not per-axis stretching", () => {
  // Width doubled, height unchanged - a naive per-axis scale would stretch height to fill the
  // new width; uniform scaling must use the constraining (smaller) axis instead.
  const scale = calculateProportionalScale(2880, 900, 1440, 900);
  assert.strictEqual(scale, 1.0); // height ratio (1.0) constrains, not width ratio (2.0)
});

test("32:9 ultra-wide against a 16:9 base is constrained by height, not width", () => {
  const scale = calculateProportionalScale(5120, 1440, 1440, 900);
  // widthRatio = 5120/1440 = 3.556, heightRatio = 1440/900 = 1.6 - height constrains
  assert.strictEqual(scale, 1.6);
});

test("scale is clamped at the minimum for a severely constrained viewport, never illegibly tiny", () => {
  const scale = calculateProportionalScale(320, 400, 1440, 900, 0.5, 2.0);
  assert.strictEqual(scale, 0.5); // raw ratio would be ~0.22 - clamped, not allowed through
});

test("scale is clamped at the maximum for an oversized viewport, never absurdly huge", () => {
  const scale = calculateProportionalScale(7680, 4320, 1440, 900, 0.5, 2.0);
  assert.strictEqual(scale, 2.0); // raw ratio would be ~4.8-5.3 - clamped
});

test("zero base dimensions are refused, never a division producing Infinity", () => {
  assert.throws(() => calculateProportionalScale(1000, 800, 0, 900));
});

test("debounce collapses a rapid resize burst into exactly one call, using the LAST arguments", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const calls: number[] = [];
  const debounced = debounce((width: number) => calls.push(width), 150);

  // Simulates a rapid drag-resize burst - many calls in quick succession, well under the
  // debounce window, matching the "rapid resize bursts" stress case this phase asks for.
  debounced(800);
  t.mock.timers.tick(30);
  debounced(850);
  t.mock.timers.tick(30);
  debounced(900);
  t.mock.timers.tick(30);
  debounced(1024); // final size the user actually settles on

  assert.strictEqual(calls.length, 0); // nothing fired yet - still within the debounce window
  t.mock.timers.tick(150);
  assert.strictEqual(calls.length, 1); // exactly one call, not four
  assert.strictEqual(calls[0], 1024); // the LAST size, not the first or an intermediate one
});

test("debounce fires again for a genuinely separate resize after the window elapses", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const calls: number[] = [];
  const debounced = debounce((width: number) => calls.push(width), 150);

  debounced(800);
  t.mock.timers.tick(150);
  debounced(1200);
  t.mock.timers.tick(150);

  assert.deepStrictEqual(calls, [800, 1200]);
});
