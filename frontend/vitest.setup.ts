/**
 * FRONTEND-VITEST-MAJOR-UPGRADE-R1: switched from the bare "@testing-library/jest-dom" import to
 * its dedicated "@testing-library/jest-dom/vitest" subpath. Proven necessary, not stylistic:
 * Vitest 5's `Assertion<T>` interface (single type parameter) replaced the older
 * `Assertion<void, HTMLElement>` two-parameter shape the bare import's ambient type augmentation
 * was written against - `tsc --noEmit` failed with "Property 'toBeInTheDocument'/'toHaveAttribute'
 * does not exist on type 'Assertion<void, HTMLElement>'" against every jest-dom version tried
 * (6.5.0 through the current 7.0.1), confirming this is Vitest 5's own type-architecture change,
 * not a jest-dom defect. jest-dom's own "./vitest" export (types/vitest.d.ts) declares
 * `interface Assertion<T = any> extends TestingLibraryMatchers<any, T> {}` - matching Vitest 5's
 * real signature exactly. Runtime behaviour is unchanged either way (both entry points register
 * the same matchers via expect.extend at runtime - confirmed by both test files already passing,
 * 14/14, before this change); this is a type-declaration-only fix.
 */
import "@testing-library/jest-dom/vitest";
