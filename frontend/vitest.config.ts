/**
 * FRONTEND-QUALITY-GATE-BLOCKERS-R1: minimal Vitest config to genuinely run the existing
 * .test.tsx component tests. Alias resolution mirrors tsconfig.json's own "@/*": ["./src/*"]
 * exactly - no new alias convention introduced. @vitejs/plugin-react is the minimal JSX/TSX
 * transform Vitest needs for these component files; nothing here changes application runtime
 * behaviour.
 */
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    // Pre-existing, already-documented split in this repo: every .test.ts file is deliberately
    // authored for Node's native `node --test` runner (zero-dependency, genuinely executed
    // already) - not Vitest. Every .test.tsx file (component tests needing jsdom + React) is
    // deliberately Vitest-shaped. Restricting `include` to .test.tsx keeps Vitest from
    // mis-collecting the node:test files.
    include: ["src/**/*.test.tsx"],
    setupFiles: ["./vitest.setup.ts"],
    // @testing-library/jest-dom's default entry point calls the ambient global expect.extend(...)
    // at import time - this must be true for that to resolve, even though the test files already
    // import expect explicitly from "vitest" themselves (harmless, additive).
    globals: true,
  },
});
