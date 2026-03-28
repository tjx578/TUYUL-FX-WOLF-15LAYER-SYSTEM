"use client";

// ============================================================
// TUYUL FX Wolf-15 — Timezone Display
// ============================================================

import { formatTime, formatLocalDate, sessionLabel } from "@/lib/timezone";
import { useClock } from "@/hooks/useClock";

interface TimezoneDisplayProps {
  compact?: boolean;
}

export function TimezoneDisplay({ compact = false }: TimezoneDisplayProps) {
  const now = useClock();

  // Hydration guard: useClock returns 0 during SSR
  if (now === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span className="num" style={{ fontSize: compact ? 13 : 16, color: "var(--text-muted)" }}>—</span>
      </div>
    );
  }

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
          {session ? `${session} SESSION` : ""}
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
        {`${formatLocalDate(now)} · ${session}`}
      </span>
    </div>
  );
}
