// ============================================================
// TUYUL FX Wolf-15 — useLivePulse Hook
// Detects value changes and triggers a CSS pulse class.
// Returns: pulse (bool) — true for 600ms on every change.
// Usage: const pulse = useLivePulse(equity);
//        <Panel className={pulse ? "live-pulse" : ""} />
// ============================================================
"use client";

import { useEffect, useRef, useState } from "react";

export function useLivePulse<T>(value: T): boolean {
  const [pulse, setPulse] = useState(false);
  const prevRef = useRef(value);

  useEffect(() => {
    if (prevRef.current !== value) {
      prevRef.current = value;
      setPulse(true);
      const id = setTimeout(() => setPulse(false), 600);
      return () => clearTimeout(id);
    }
  }, [value]);

  return pulse;
}
