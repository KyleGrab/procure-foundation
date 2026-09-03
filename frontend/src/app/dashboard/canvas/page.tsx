import { Suspense } from "react";
import { ProcureIQCanvas } from "@/components/canvas/ProcureIQCanvas";

// Suspense is required here, not optional - ProcureIQCanvas uses useSearchParams() (to read
// ?lens= from gateway deep links), and Next.js's App Router genuinely fails `next build` without
// a Suspense boundary around any client component that calls it.
export default function CanvasPage() {
  return (
    <Suspense fallback={null}>
      <ProcureIQCanvas />
    </Suspense>
  );
}
