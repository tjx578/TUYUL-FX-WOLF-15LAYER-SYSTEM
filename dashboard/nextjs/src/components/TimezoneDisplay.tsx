"use client";

// ============================================================
// TUYUL FX Wolf-15 — TimezoneDisplay
// ============================================================

import { useEffect, useState } from "react";
import { formatTime, sessionLabel, nowInTz } from "@/lib/timezone";

interface TimezoneDisplayProps {
  compact?: boolean;
}

export function TimezoneDisplay({ compact = false }: TimezoneDisplayProps) {
  const [time, setTime] = useState("");
  const [session, setSession] = useState("");

  useEffect(() => {
    const tick = () => {
      setTime(formatTime(nowInTz()));
      setSession(sessionLabel());
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  if (compact) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          className="num"
          style={{
            fontSize: 11,
            color: "var(--text-secondary)",
            letterSpacing: "0.04em",
          }}
        >
          {time || "—"}
        </span>
        <span
          className="badge badge-muted"
          style={{ fontSize: 8 }}
        >
          {session}
        </span>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "6px 12px",
        background: "var(--bg-card)",
        border: "1px solid var(--bg-border)",
        borderRadius: 6,
      }}
    >
      <span
        className="num"
        style={{
          fontSize: 14,
          fontWeight: 700,
          color: "var(--text-primary)",
          letterSpacing: "0.04em",
        }}
      >
        {time || "—"}
      </span>
      <span
        className="badge badge-blue"
        style={{ fontSize: 10 }}
      >
        {session}
      </span>
      <span
        style={{
          fontSize: 10,
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
        }}
      >
        GMT+8
      </span>
    </div>
  );
}

// Keep default export for backward compat
export default TimezoneDisplay;
