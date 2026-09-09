"use client";

// ============================================================
// TUYUL FX Wolf-15 — Route Transition Engine
// Provides institutional-feel page transitions via Framer Motion.
// Mode: fade + slight vertical slide
//
// FIXED: Removed AnimatePresence to prevent blocking navigation.
// AnimatePresence with App Router can cause issues where exit
// animations prevent new pages from rendering.
// ============================================================

import { motion } from "framer-motion";
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
    <motion.div
      key={pathname}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.25,
        ease: [0.4, 0, 0.2, 1],
      }}
      style={{ minHeight: "100%", width: "100%" }}
    >
      {children}
    </motion.div>
  );
}
