"use client";

// ============================================================
// TUYUL FX Wolf-15 — Route Transition Engine
// Provides institutional-feel page transitions via Framer Motion.
// Mode: fade + slight vertical slide + blur layer refresh
// ============================================================

import { AnimatePresence, motion } from "framer-motion";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

export default function RouteTransition({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  // ── Smooth scroll-to-top on every route change ──
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [pathname]);

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={pathname}
        initial={{ opacity: 0, y: 10, filter: "blur(4px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        exit={{ opacity: 0, y: -10, filter: "blur(4px)" }}
        transition={{
          duration: 0.35,
          ease: [0.4, 0, 0.2, 1],
        }}
        // Ensure layout doesn't reflow during transition
        style={{ minHeight: "100%", width: "100%" }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
