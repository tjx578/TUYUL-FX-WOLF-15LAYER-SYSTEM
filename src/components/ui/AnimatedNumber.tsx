// ============================================================
// TUYUL FX Wolf-15 — AnimatedNumber (PnL Counter Engine)
// CSS-only smooth number transition + directional color flash.
// Up → emerald flash | Down → red flash
// Production-safe: degrades gracefully if value unchanged.
//
// PERF AUDIT (Part G): Zero external animation library dependencies.
// Uses requestAnimationFrame for number interpolation (no React reconciliation),
// CSS keyframes for color flash (no JS overhead during animation).
// ============================================================
"use client";

import { memo, useEffect, useRef, useState, useCallback } from "react";

interface AnimatedNumberProps {
  value: number;
  decimals?: number;
  /** Optional prefix, e.g. "$" or "+" */
  prefix?: string;
  /** Duration in milliseconds */
  duration?: number;
  className?: string;
  /** Enable directional color flash on change */
  directionFlash?: boolean;
}

function AnimatedNumber({
  value,
  decimals = 2,
  prefix = "",
  duration = 600,
  className,
  directionFlash = false,
}: AnimatedNumberProps) {
  const [display, setDisplay] = useState(value);
  const [flashClass, setFlashClass] = useState<string | null>(null);
  const prevRef = useRef(value);
  const rafRef = useRef<number | null>(null);
  const startTimeRef = useRef<number | null>(null);
  const fromRef = useRef(value);

  // Cleanup RAF on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, []);

  // easeOutCubic for smooth deceleration
  const easeOutCubic = useCallback((t: number) => 1 - Math.pow(1 - t, 3), []);

  useEffect(() => {
    const from = prevRef.current;
    prevRef.current = value;

    // Skip animation for identical values
    if (from === value) return;

    // Cancel any ongoing animation
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
    }

    // Trigger CSS flash class
    if (directionFlash) {
      const dir = value > from ? "flash-up" : "flash-down";
      setFlashClass(dir);
    }

    // Setup RAF-based number interpolation
    fromRef.current = from;
    startTimeRef.current = null;

    const animate = (timestamp: number) => {
      if (startTimeRef.current === null) {
        startTimeRef.current = timestamp;
      }

      const elapsed = timestamp - startTimeRef.current;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easeOutCubic(progress);

      const currentValue = fromRef.current + (value - fromRef.current) * easedProgress;
      setDisplay(currentValue);

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      } else {
        rafRef.current = null;
        startTimeRef.current = null;
      }
    };

    rafRef.current = requestAnimationFrame(animate);
  }, [value, duration, directionFlash, easeOutCubic]);

  // Clear flash class after animation completes (600ms matches CSS keyframe)
  useEffect(() => {
    if (flashClass === null) return;

    const timer = setTimeout(() => {
      setFlashClass(null);
    }, 600);

    return () => clearTimeout(timer);
  }, [flashClass]);

  // Combine className with flash class
  const combinedClass = [className, flashClass].filter(Boolean).join(" ") || undefined;

  return (
    <span className={combinedClass}>
      {prefix}
      {display.toFixed(decimals)}
    </span>
  );
}

// Re-export as memo to avoid re-renders from parent on hot-path (tick-rate price updates).
// CSS-only flash animation: uses .flash-up / .flash-down classes defined in globals.css
// with @keyframes value-flash-up / value-flash-down (no JS animation overhead).
export default memo(AnimatedNumber);
