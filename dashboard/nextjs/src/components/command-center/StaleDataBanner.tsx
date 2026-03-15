"use client";

// ============================================================
// TUYUL FX Wolf-15 — StaleDataBanner
// PRD: Command Center — stale/degraded indicator
// Shows when WS is disconnected or verdicts are stale
// ============================================================

import { useEffect, useState } from "react";

interface StaleDataBannerProps {
  isStale: boolean;
  isSystemDegraded: boolean;
  wsStatus: string;
  dataErrors: string[];
}

export default function StaleDataBanner({
  isStale,
  isSystemDegraded,
  wsStatus,
  dataErrors,
}: StaleDataBannerProps) {
  const [staleSince, setStaleSince] = useState<number | null>(null);
  const [staleSeconds, setStaleSeconds] = useState(0);

  const shouldShow = isStale || isSystemDegraded;

  useEffect(() => {
    if (shouldShow && staleSince === null) {
      setStaleSince(Date.now());
    }
    if (!shouldShow) {
      setStaleSince(null);
      setStaleSeconds(0);
    }
  }, [shouldShow, staleSince]);

  useEffect(() => {
    if (staleSince === null) return;
    const interval = setInterval(() => {
      setStaleSeconds(Math.floor((Date.now() - staleSince) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [staleSince]);

  if (!shouldShow) return null;

  const isOffline = wsStatus === "DISCONNECTED";
  const staleLabel =
    staleSeconds < 60
      ? `${staleSeconds}s`
      : `${Math.floor(staleSeconds / 60)}m ${staleSeconds % 60}s`;

  const message = isOffline
    ? "Backend connection lost — operating with last known data."
    : wsStatus === "RECONNECTING"
    ? "Live channel reconnecting — verdicts may be stale."
    : "Verdict data is stale — live feed not responding.";

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 14px",
        borderRadius: "var(--radius-sm)",
        border: `1px solid ${isOffline ? "var(--border-danger)" : "var(--border-warn)"}`,
        borderLeft: `3px solid ${isOffline ? "var(--red)" : "var(--yellow)"}`,
        background: isOffline ? "rgba(255,61,87,0.05)" : "rgba(255,215,64,0.05)",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: isOffline ? "var(--red)" : "var(--yellow)",
          flexShrink: 0,
          animation: "pulse-dot 1.5s ease-in-out infinite",
        }}
        aria-hidden="true"
      />
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          fontWeight: 800,
          color: isOffline ? "var(--red)" : "var(--yellow)",
          letterSpacing: "0.08em",
          flexShrink: 0,
        }}
      >
        {isOffline ? "OFFLINE" : "STALE DATA"}
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          color: "var(--text-muted)",
          padding: "2px 6px",
          borderRadius: 3,
          background: "rgba(255,255,255,0.05)",
          flexShrink: 0,
        }}
      >
        {staleLabel}
      </span>
      <span style={{ fontSize: 11, color: "var(--text-secondary)", flex: 1 }}>
        {message}
      </span>
      {dataErrors.length > 0 && (
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            color: "var(--text-muted)",
            flexShrink: 0,
          }}
        >
          FAILING: {dataErrors.join(", ")}
        </span>
      )}
    </div>
  );
}
