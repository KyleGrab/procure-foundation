import "./globals.css";
import type { Metadata } from "next";
import { AppBackground } from "@/components/layout/AppBackground";

export const metadata: Metadata = {
  title: "ProcureIQ",
  description: "Procurement intelligence and margin protection platform",
};

// Global background system (PROCUREIQ-APP-BACKGROUND-R1): rendered once, here, outside
// `{children}` so it never unmounts across a client-side navigation - see AppBackground's own
// docstring for why that's what actually keeps this continuous rather than flashing between
// routes. The body's own bg is the same token as a same-color fallback for the instant before
// AppBackground paints (SSR sends both in the same response, so in practice this is never
// visible) - text-slate-100 matches the light-on-dark text color already used throughout the
// existing dark UI (HomeGateway, the dashboard shell, login). A route needing dark-on-light
// instead (the /price-reviews subtree - see its own layout.tsx) sets its own opaque surface and
// text color, which simply overrides this by normal CSS inheritance/stacking.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="relative min-h-screen bg-[color:var(--app-bg-base)] text-slate-100 antialiased">
        <AppBackground />
        {children}
      </body>
    </html>
  );
}
