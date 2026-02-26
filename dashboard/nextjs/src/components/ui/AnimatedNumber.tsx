// ============================================================
// TUYUL FX Wolf-15 — AnimatedNumber (PnL Counter Engine)
// Smooth number transition using framer-motion animate.
// Production-safe: degrades gracefully if value unchanged.
// ============================================================
"use client";

import { useEffect, useRef, useState } from "react";
import { animate } from "framer-motion";

interface AnimatedNumberProps {
  value: number;
  decimals?: number;
  /** Optional prefix, e.g. "$" or "+" */
  prefix?: string;
  /** Duration in seconds */
  duration?: number;
  className?: string;
}

export default function AnimatedNumber({
  value,
  decimals = 2,
  prefix = "",
  duration = 0.6,
  className,
}: AnimatedNumberProps) {
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);

  useEffect(() => {
    const from = prevRef.current;
    prevRef.current = value;

    // Skip animation for identical values
    if (from === value) return;

    const controls = animate(from, value, {
      duration,
      ease: "easeOut",
      onUpdate: (v) => setDisplay(v),
    });

    return controls.stop;
  }, [value, duration]);

  return (
    <span className={className}>
      {prefix}
      {display.toFixed(decimals)}
    </span>
  );
}
