"use client";

// ============================================================
// TUYUL FX Wolf-15 — Route Transition Engine
// Provides institutional-feel page transitions via Framer Motion.
// Mode: fade + slight vertical slide + blur layer refresh
//
// NOTE: Uses mode="popLayout" instead of "wait" to avoid
// React 19 fiber null-assertion crash (n || rD(e, !0)).
// "popLayout" keeps both old and new children mounted briefly,
// preventing the stale-fiber unmount race in concurrent mode.
//
// FIX: The `layout` prop has been intentionally removed from
// motion.div. Combining `layout` with `AnimatePresence
// mode="popLayout"` and Next.js App Router concurrent mode
// triggers a React fiber null-assertion crash (n || rD(e, !0))
// on every client-side navigation, preventing all routes except
// the initial page from loading.
// ============================================================

import React, { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { usePathname } from "next/navigation";

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
    <AnimatePresence mode="popLayout">
      <motion.div
        key={pathname}
        initial={{ opacity: 0, y: 10, filter: "blur(4px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        exit={{ opacity: 0, y: -10, filter: "blur(4px)" }}
        transition={{
          duration: 0.3,
          ease: [0.4, 0, 0.2, 1],
        }}
        style={{ minHeight: "100%", width: "100%" }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
