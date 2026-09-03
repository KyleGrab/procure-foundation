/**
 * Stress/edge-case tests for useWindowDimensions and ViewportScaledContainer. WRITTEN, NOT
 * EXECUTED - same category as FxExposureCard.test.tsx: needs @testing-library/react + jsdom
 * (window.innerWidth/innerHeight mocking, real layout measurement for overflow/text-wrapping
 * assertions), none of which could be installed (npm install confirmed blocked, 403 Forbidden).
 *
 * The pure math these tests exercise (classifyAspectRatio, calculateProportionalScale, debounce)
 * IS genuinely tested and passing - see viewport-scaling.test.ts, 14/14, including the exact
 * 32:9/9:16/iPad-portrait/extreme-vertical-strip cases requested here. What's NOT and CANNOT be
 * verified in this sandbox is what a real browser actually DOES with those numbers - whether
 * text genuinely wraps instead of overflowing, whether a data grid clips at 9:16, whether
 * high-DPI/retina scaling (devicePixelRatio) interacts correctly with the CSS custom property
 * approach. That requires an actual rendering engine, which does not exist here. Writing tests
 * that claim to "guarantee zero layout breakage" without a real browser to run them against
 * would be asserting something I have no way to have verified - so this file documents the
 * scenarios precisely without overclaiming their result.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { renderHook, act } from "@testing-library/react";
import { useWindowDimensions } from "@/lib/useWindowDimensions";
import { ViewportScaledContainer } from "@/components/common/ViewportScaledContainer";

function mockViewport(width: number, height: number) {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width });
  Object.defineProperty(window, "innerHeight", { writable: true, configurable: true, value: height });
}

describe("useWindowDimensions - extreme aspect ratios", () => {
  it("detects a 32:9 ultra-wide monitor (5120x1440) correctly", () => {
    mockViewport(5120, 1440);
    const { result } = renderHook(() => useWindowDimensions());
    act(() => window.dispatchEvent(new Event("resize")));
    expect(result.current.category).toBe("ultra-wide");
  });

  it("detects a 9:16 mobile viewport (390x844) correctly", () => {
    mockViewport(390, 844);
    const { result } = renderHook(() => useWindowDimensions());
    act(() => window.dispatchEvent(new Event("resize")));
    expect(result.current.category).toBe("portrait");
  });

  it("detects a vertical tablet (820x1180) correctly", () => {
    mockViewport(820, 1180);
    const { result } = renderHook(() => useWindowDimensions());
    act(() => window.dispatchEvent(new Event("resize")));
    expect(result.current.category).toBe("portrait");
  });

  it("collapses a rapid resize burst (10 events in under the debounce window) into one state update", () => {
    mockViewport(1440, 900);
    const { result } = renderHook(() => useWindowDimensions());
    act(() => {
      for (let i = 0; i < 10; i++) {
        mockViewport(1440 + i * 10, 900);
        window.dispatchEvent(new Event("resize"));
      }
    });
    // Only the FINAL size should be reflected once the debounce window elapses - this is a
    // behavioral assertion about the hook's debounce wiring, which viewport-scaling.test.ts's
    // real, executed debounce tests already prove correct in isolation; this test would confirm
    // the hook actually uses that already-proven debounce correctly, not re-prove debounce itself.
    expect(result.current.width).toBe(1440 + 9 * 10);
  });
});

describe("ViewportScaledContainer - layout boundary scenarios (documented, not verified)", () => {
  it.todo(
    "text within the container wraps rather than overflowing at 9:16 (390x844) - " +
    "requires real layout measurement (getBoundingClientRect/getComputedStyle against an actual " +
    "rendering engine); jsdom does not perform real layout, so even with jsdom installed this " +
    "specific assertion would need a real browser (Playwright/Cypress) to be meaningful, not RTL+jsdom",
  );

  it.todo(
    "a data grid does not clip its rightmost column at 32:9 ultra-wide (5120x1440) - " +
    "same real-layout-measurement requirement as above",
  );

  it.todo(
    "high-DPI/retina scaling (devicePixelRatio: 2 or 3) does not double-apply on top of " +
    "--viewport-scale - needs verification that the CSS custom property approach (real layout " +
    "units) is genuinely independent of devicePixelRatio (a rendering-resolution concern, not a " +
    "CSS-pixel layout concern) rather than assumed independent",
  );

  it("sets data-aspect-category to the correct value for a mocked ultra-wide viewport", () => {
    mockViewport(5120, 1440);
    render(<ViewportScaledContainer>content</ViewportScaledContainer>);
    const container = screen.getByText("content").parentElement;
    expect(container).toHaveAttribute("data-aspect-category", "ultra-wide");
  });
});
