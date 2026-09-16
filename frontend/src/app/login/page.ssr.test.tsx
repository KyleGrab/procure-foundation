// @vitest-environment node
/**
 * Genuine server-rendering regression test. Deliberately forced into vitest's plain "node"
 * environment (not the project default jsdom - see vitest.config.ts) for this one file, so
 * window/document/sessionStorage are truly undefined here, exactly like real Next.js server
 * rendering of a "use client" page's initial HTML. page.test.tsx (jsdom) already covers
 * click-interaction behavior; this file's only job is to catch this page - or the demo-mode
 * guards it calls during render - reaching for a browser-only API outside an event
 * handler/effect, which jsdom would silently paper over.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderToString } from "react-dom/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import LoginPage from "./page";

describe("LoginPage - server rendering", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("this file's own environment is genuinely browser-API-free, or the tests below prove nothing", () => {
    expect(typeof window).toBe("undefined");
    expect(typeof document).toBe("undefined");
    expect(typeof sessionStorage).toBe("undefined");
  });

  it("renders to a string without throwing with demo mode off", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "");
    let html = "";
    expect(() => {
      html = renderToString(<LoginPage />);
    }).not.toThrow();
    expect(html).toContain("Log in");
    expect(html).not.toContain("Continue with demo sign-in");
  });

  it("renders to a string without throwing with development AND the flag both set", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    let html = "";
    expect(() => {
      html = renderToString(<LoginPage />);
    }).not.toThrow();
    expect(html).toContain("Continue with demo sign-in");
  });

  it("renders to a string without throwing, and never includes the bypass, for a production build with the flag baked in - the exact case a prior report found broken", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    let html = "";
    expect(() => {
      html = renderToString(<LoginPage />);
    }).not.toThrow();
    expect(html).toContain("Log in");
    expect(html).not.toContain("Continue with demo sign-in");
  });
});
