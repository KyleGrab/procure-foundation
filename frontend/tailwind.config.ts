import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // PROCUREIQ-BLUE-SURFACE-R1 (retinted dark under R2 - see globals.css's --app-border-light):
      // retints every bare `border`/`border-t`/`border-b`/etc. utility (one with no explicit
      // color suffix) to this token instead of Tailwind's own gray-200 default. Confirmed by grep
      // before this change: every such bare usage in this codebase lives in the /price-reviews
      // subtree - nowhere else in the app relies on the Tailwind default border color, so this
      // has no effect anywhere else.
      borderColor: {
        DEFAULT: "var(--app-border-light)",
      },
    },
  },
  plugins: [],
};
export default config;
