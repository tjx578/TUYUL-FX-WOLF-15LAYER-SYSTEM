"use client";

import { useRef } from "react";

// Module-level timestamp registry (shared across all hook instances).
// Replaces the former useActionThrottleStore global Zustand store.
const _timestamps: Record<string, number> = {};

export function useActionThrottle(key: string, minIntervalMs = 1_500) {
  // Keep a stable ref to the key so callbacks close over the right value.
  const keyRef = useRef(key);
  keyRef.current = key;

  const getRemainingMs = () => {
    const last = _timestamps[keyRef.current];
    if (!last) {
      return 0;
    }
    const elapsed = Date.now() - last;
    return Math.max(0, minIntervalMs - elapsed);
  };

  const isThrottled = () => getRemainingMs() > 0;

  const markNow = () => {
    _timestamps[keyRef.current] = Date.now();
  };

  return {
    getRemainingMs,
    isThrottled,
    markNow,
  };
}