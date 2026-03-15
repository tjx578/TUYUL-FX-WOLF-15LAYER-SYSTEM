// ============================================================
// TUYUL FX Wolf-15 — AnimatedNumber (PnL Counter Engine)
// Smooth number transition + directional color flash.
// Up → emerald flash | Down → red flash
// Production-safe: degrades gracefully if value unchanged.
//
// PERF AUDIT (Part G): Only hot-path framer-motion usage.
// Mitigations: React.memo(), imperative animate() (no reconciliation),
// conditional motion.span (only renders on direction change).
// Other framer-motion consumers (VerdictCard, RiskGauge, micro, EquityChart,
// RouteTransition) are non-hot-path — update frequencies 2s–15s+.
// ============================================================
"use client";

import { memo, useEffect, useRef, useState } from "react";
import { animate, motion } from "framer-motion";

interface AnimatedNumberProps {
  value: number;
  decimals?: number;
  /** Optional prefix, e.g. "$" or "+" */
  prefix?: string;
  /** Duration in seconds */
  duration?: number;
  className?: string;
  /** Enable directional color flash on change */
  directionFlash?: boolean;
}

function AnimatedNumber({
  value,
  decimals = 2,
  prefix = "",
  duration = 0.6,
  className,
  directionFlash = false,
}: AnimatedNumberProps) {
  const [display, setDisplay] = useState(value);
  const [direction, setDirection] = useState<"up" | "down" | null>(null);
  const prevRef = useRef(value);

  useEffect(() => {
    const from = prevRef.current;
    prevRef.current = value;

    // Skip animation for identical values
    if (from === value) return;

    if (directionFlash) {
      setDirection(value > from ? "up" : "down");
    }

    const controls = animate(from, value, {
      duration,
      ease: "easeOut",
      onUpdate: (v) => setDisplay(v),
    });

    return controls.stop;
  }, [value, duration, directionFlash]);

  if (directionFlash && direction !== null) {
    return (
      <motion.span
        className={className}
        animate={{
          color:
            direction === "up"
              ? ["#00F5A0", "var(--text-primary)"]
              : ["#FF4D4F", "var(--text-primary)"],
        }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        onAnimationComplete={() => setDirection(null)}
      >
        {prefix}
        {display.toFixed(decimals)}
      </motion.span>
    );
  }

  return (
    <span className={className}>
      {prefix}
      {display.toFixed(decimals)}
    </span>
  );
}

// Re-export as memo to avoid re-renders from parent on hot-path (tick-rate price updates).
// framer-motion audit: animate() is imperative (no React reconciliation cost),
// motion.span only renders when directionFlash fires (conditional).
export default memo(AnimatedNumber);
