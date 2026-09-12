/**
 * FRONTEND-QUALITY-GATE-BLOCKERS-R1: existing test files already `import
 * "@testing-library/jest-dom"` directly (idempotent) - this file exists only so a future test
 * file doesn't have to remember to do the same, per Vitest's own setupFiles convention.
 */
import "@testing-library/jest-dom";
