"use client";

// ============================================================
// TUYUL FX Wolf-15 — Timezone Display
// ============================================================

import { useEffect, useState } from "react";
import { formatTime, formatDate, sessionLabel } from "@/lib/timezone";

interface TimezoneDisplayProps {
  compact?: boolean;
}

export function TimezoneDisplay({ compact = false }: TimezoneDisplayProps) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const now = Date.now();
  const session = sessionLabel();

  if (compact) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="num"
          style={{
            fontSize: 13,
            color: "var(--accent)",
            fontWeight: 700,
          }}
        >
          {formatTime(now)}
        </span>
        <span
          style={{
            fontSize: 10,
            color: "var(--text-muted)",
            letterSpacing: "0.06em",
          }}
        >
          {session} SESSION
        </span>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: 2,
      }}
    >
      <span
        className="num"
        style={{ fontSize: 16, color: "var(--text-primary)", fontWeight: 700 }}
      >
        {formatTime(now)}
      </span>
      <span
        style={{ fontSize: 11, color: "var(--text-muted)", letterSpacing: "0.04em" }}
      >
        {formatDate(now)} · {session}
      </span>
    </div>
  );
}
