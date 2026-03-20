"use client";

/**
 * TUYUL FX Wolf-15 — Data Freshness Badge
 *
 * Honest UX indicator for realtime data freshness.
 * Shows traders exactly how stale their data is — critical for trust.
 *
 * States:
 *   - LIVE (green): Data updated within threshold
 *   - STALE (yellow): Data is older than threshold
 *   - DISCONNECTED (red): No connection to backend
 */

import { useEffect, useState } from "react";

interface DataFreshnessBadgeProps {
  /** Timestamp (ms) of last data update */
  lastUpdatedAt: number | null;
  /** Whether the WebSocket connection is active */
  connected: boolean;
  /** Threshold in seconds before data is considered stale (default: 5s) */
  staleThresholdSec?: number;
  /** Optional label to show before the status */
  label?: string;
}

export function DataFreshnessBadge({
  lastUpdatedAt,
  connected,
  staleThresholdSec = 5,
  label,
}: DataFreshnessBadgeProps) {
  const [now, setNow] = useState(Date.now());

  // Update clock every second for accurate age display
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, []);

  if (!lastUpdatedAt) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {label && (
          <span
            style={{
              fontSize: 9,
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.08em",
              color: "var(--text-muted)",
            }}
          >
            {label}
          </span>
        )}
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            padding: "4px 8px",
            borderRadius: 6,
            background: "rgba(255,255,255,0.04)",
            fontSize: 9,
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.08em",
            color: "var(--text-muted)",
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--text-muted)",
              opacity: 0.5,
            }}
          />
          NO DATA
        </span>
      </div>
    );
  }

  const ageSec = Math.max(0, Math.floor((now - lastUpdatedAt) / 1000));
  const isStale = ageSec >= staleThresholdSec;
  const isDisconnected = !connected;

  // Determine visual state
  let statusColor = "var(--green)";
  let statusLabel = "LIVE";
  let dotAnimation = true;

  if (isDisconnected) {
    statusColor = "var(--red)";
    statusLabel = "DISCONNECTED";
    dotAnimation = false;
  } else if (isStale) {
    statusColor = "var(--yellow, #FFB800)";
    statusLabel = `STALE ${ageSec}s`;
    dotAnimation = false;
  } else {
    statusLabel = `LIVE ${ageSec}s`;
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      {label && (
        <span
          style={{
            fontSize: 9,
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.08em",
            color: "var(--text-muted)",
          }}
        >
          {label}
        </span>
      )}
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          padding: "4px 8px",
          borderRadius: 6,
          background: isDisconnected
            ? "rgba(255,71,87,0.12)"
            : isStale
              ? "rgba(255,184,0,0.12)"
              : "rgba(0,245,160,0.12)",
          fontSize: 9,
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.08em",
          fontWeight: 600,
          color: statusColor,
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: statusColor,
            animation: dotAnimation ? "pulse-dot 1.5s ease-in-out infinite" : "none",
          }}
        />
        {statusLabel}
      </span>
    </div>
  );
}

export default DataFreshnessBadge;
