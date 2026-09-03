/**
 * Gateway-only truck transition (white-label splash screen). Deliberately NOT used anywhere in
 * the inner app - components/ui/InteractiveMetricCard.tsx's "no mascot/character assets" rule
 * still applies to the real dashboard; this is scoped to the gateway layer only, per the
 * explicit design rule for this feature.
 *
 * Default truck asset is now real: public/images/pps-logistics-truck-side-removebg-preview.png,
 * a genuine 1774x887px (2:1) side-profile shot - confirmed by actually opening the file and
 * checking its dimensions, not assumed. The 2:1 box below matches that real aspect ratio exactly
 * so `object-contain` isn't compensating for a guessed box shape. A side-facing profile is
 * exactly the right asset for this transition's left-to-right slide - a front-facing truck would
 * look wrong translating sideways, a side profile reads correctly the whole way across.
 *
 * Falls back to a plain lucide-react Truck icon in a branded circle only if `truckImageSrc`
 * isn't supplied or fails to load - not the normal path anymore now that a real asset exists,
 * but kept so a different white-label deployment without its own truck image still works.
 */
"use client";

import { useState } from "react";
import Image from "next/image";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Truck } from "lucide-react";
import { DEFAULT_CLIENT_BRAND, type ClientBrand } from "@/types/client-brand";

interface TruckTransitionProps {
  active: boolean;
  clientBrand?: ClientBrand;
  onComplete: () => void;
}

function useIsTouchDevice(): boolean {
  const [isTouch, setIsTouch] = useState(false);
  if (typeof window !== "undefined" && !isTouch) {
    const touch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
    if (touch) setIsTouch(true);
  }
  return isTouch;
}

function TruckGlyph({ clientBrand }: { clientBrand: ClientBrand }) {
  const [imageFailed, setImageFailed] = useState(false);

  if (!clientBrand.truckImageSrc || imageFailed) {
    return (
      <div
        className="flex h-24 w-24 items-center justify-center rounded-2xl shadow-[0_0_30px_rgba(99,102,241,0.35)]"
        style={{ backgroundColor: clientBrand.primaryColor }}
      >
        <Truck className="h-12 w-12 text-white" aria-hidden="true" />
      </div>
    );
  }

  return (
    // 2:1 box matching the real asset's actual aspect ratio (1774x887px, confirmed) - not a
    // guessed shape that object-contain has to letterbox around.
    <div className="relative h-32 w-64">
      <Image
        src={clientBrand.truckImageSrc}
        alt=""
        fill
        sizes="256px"
        className="object-contain drop-shadow-[0_16px_20px_rgba(0,0,0,0.4)]"
        onError={() => setImageFailed(true)}
        priority
      />
    </div>
  );
}

/**
 * One real, working transition - not the multi-stage choreography from the earlier fabricated
 * draft. Reduced-motion and touch/mobile both skip straight to onComplete: a truck sliding
 * across a small phone screen adds nothing and prefers-reduced-motion means exactly what it says.
 */
export function TruckTransition({ active, clientBrand = DEFAULT_CLIENT_BRAND, onComplete }: TruckTransitionProps) {
  const prefersReducedMotion = useReducedMotion();
  const isTouch = useIsTouchDevice();
  const skipAnimation = Boolean(prefersReducedMotion) || isTouch;

  return (
    <AnimatePresence>
      {active && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center overflow-hidden bg-[#0B0D17]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: skipAnimation ? 0 : 0.2 }}
          onAnimationComplete={() => {
            if (skipAnimation) onComplete();
          }}
          aria-live="polite"
          aria-label={`Opening ${clientBrand.name} operations workspace`}
        >
          {skipAnimation ? null : (
            <motion.div
              initial={{ x: "-25vw" }}
              animate={{ x: "125vw" }}
              transition={{ duration: 1.1, ease: [0.32, 0.72, 0.35, 1] }}
              onAnimationComplete={onComplete}
              className="will-change-transform"
            >
              <TruckGlyph clientBrand={clientBrand} />
            </motion.div>
          )}
          <span className="sr-only">Loading operations workspace</span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
