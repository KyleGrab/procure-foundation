/**
 * Covers the demo sign-in path added for PROCUREIQ-PRICE-REVIEW-DEMO-UX-R3/R5: it must be
 * genuinely client-only (never calls the real /auth/login endpoint), gated by
 * shouldShowDemoLoginBypass's stricter AND (NODE_ENV==="development" AND
 * NEXT_PUBLIC_DEMO_MODE==="true", both required - see that guard's own docstring for why this
 * differs from demo-mode.ts's OR-gated isDemoModeEnabled used elsewhere in this feature), and
 * must never leave a stale real access token lying around. fillDevDemoCredentials' own
 * pre-existing behavior (real backend login) is untouched and not re-tested here.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import LoginPage from "./page";

describe("LoginPage - demo sign-in", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    pushMock.mockClear();
    sessionStorage.clear();
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    vi.unstubAllEnvs();
  });

  it("shows the demo sign-in path only when development AND the explicit flag are both set", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    render(<LoginPage />);
    expect(screen.getByRole("button", { name: "Continue with demo sign-in" })).toBeInTheDocument();
  });

  it("hides it in local development with the flag NOT set - dev alone is not enough", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "");
    render(<LoginPage />);
    expect(screen.queryByRole("button", { name: "Continue with demo sign-in" })).not.toBeInTheDocument();
  });

  it("hides it in a REAL PRODUCTION BUILD even with NEXT_PUBLIC_DEMO_MODE='true' baked in - the flag alone is not enough, this is the exact case a prior report found broken", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    render(<LoginPage />);
    expect(screen.queryByRole("button", { name: "Continue with demo sign-in" })).not.toBeInTheDocument();
    // The real login form must still be there - hiding the bypass must never take the page with it.
    expect(screen.getByRole("button", { name: "Log in" })).toBeInTheDocument();
  });

  it("hides it in a production build with no demo-mode flag at all - the default deployment case", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "");
    render(<LoginPage />);
    expect(screen.queryByRole("button", { name: "Continue with demo sign-in" })).not.toBeInTheDocument();
  });

  it("navigates straight to the gateway without ever calling the real login endpoint", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    render(<LoginPage />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with demo sign-in" }));
    expect(pushMock).toHaveBeenCalledWith("/welcome");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("clears any stale real access token before entering the demo gateway, and sets no Authorization-bearing value", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    sessionStorage.setItem("procureiq_access_token", "stale-real-token");
    render(<LoginPage />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with demo sign-in" }));
    expect(sessionStorage.getItem("procureiq_access_token")).toBeNull();
  });
});
