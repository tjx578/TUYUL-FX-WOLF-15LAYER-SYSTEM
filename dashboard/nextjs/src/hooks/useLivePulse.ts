// ============================================================
// TUYUL FX Wolf-15 — useLivePulse Hook
// Detects value changes and triggers a CSS pulse class.
// Returns: pulse (bool) — true for 600ms on every change.
// Usage: const pulse = useLivePulse(equity);
//        <Panel className={pulse ? "live-pulse" : ""} />
// ============================================================
"use client";

import { useEffect, useState } from "react";

export function useLivePulse<T>(value: T): boolean {
  const [pulse, setPulse] = useState(false);
  const [prev, setPrev] = useState<T>(value);

  useEffect(() => {
    if (prev !== value) {
      setPulse(true);
      setPrev(value);

      const timeout = setTimeout(() => {
        setPulse(false);
      }, 600);

      return () => clearTimeout(timeout);
    }
  }, [value, prev]);

  return pulse;
}
