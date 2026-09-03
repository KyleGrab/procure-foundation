/**
 * Minimal shadcn/ui-compatible Skeleton. Hand-written, not generated via `npx shadcn-ui add
 * skeleton` - that CLI needs network access this sandbox doesn't have. API-compatible with the
 * real shadcn Skeleton (same className prop, same usage pattern) so swapping in the generated
 * version later is a drop-in replacement, not a rewrite of anything that uses it.
 */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-[#1F2438] ${className}`} />;
}
