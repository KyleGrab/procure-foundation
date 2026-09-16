import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // PROCUREIQ-BLUE-SURFACE-R1: retints every bare `border`/`border-t`/`border-b`/etc. utility
      // (one with no explicit color suffix) to the app's light blue-tinted border token instead
      // of Tailwind's own gray-200 default. Confirmed by grep before this change: every such bare
      // usage in this codebase lives in the /price-reviews subtree (the one part of the app still
      // built on a light surface) - nowhere else in the app relies on the Tailwind default border
      // color, so this has no effect anywhere else.
      borderColor: {
        DEFAULT: "var(--app-border-light)",
      },
    },
  },
  plugins: [],
};
export default config;
