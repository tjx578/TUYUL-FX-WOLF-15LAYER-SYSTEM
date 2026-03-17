"use client";

// ============================================================
// TUYUL FX Wolf-15 — GlobalStatusStrip
// PRD: Command Center — real-time status bar across top
// Shows: BACKEND | LIVE FEED | ENGINE | OPEN TRADES | MODE
// ============================================================

import type { WsConnectionStatus } from "@/lib/realtime/connectionState";

interface GlobalStatusStripProps {
  health: { status: string } | undefined;
  wsStatus: WsConnectionStatus;
  mode: string;
  executionState: string | undefined;
  openTradeCount: number;
  isStale: boolean;
}

function statusColor(status: string) {
  if (status === "SAFE" || status === "ok" || status === "OK") return "var(--green)";
  if (status === "WARNING" || status === "WARN") return "var(--yellow)";
  if (status === "CRITICAL" || status === "error") return "var(--red)";
  return "var(--text-muted)";
}

export default function GlobalStatusStrip({
  health,
  wsStatus,
  mode,
  executionState,
  openTradeCount,
  isStale,
}: GlobalStatusStripProps) {
  const backendOk = health?.status === "ok";
  const degraded = mode === "DEGRADED";

  const items = [
    {
      label: "BACKEND",
      value: health ? health.status.toUpperCase() : "UNKNOWN",
      color: health ? statusColor(health.status) : "var(--text-faint)",
      pulse: backendOk,
    },
    {
      label: "LIVE FEED",
      value: isStale ? "STALE" : wsStatus,
      color:
        wsStatus === "LIVE" && !isStale
          ? "var(--green)"
          : isStale || wsStatus === "RECONNECTING" || wsStatus === "CONNECTING" || wsStatus === "DEGRADED" || wsStatus === "STALE"
            ? "var(--yellow)"
            : "var(--red)",
      pulse: wsStatus === "LIVE" && !isStale,
    },
    {
      label: "ENGINE",
      value: executionState ?? "—",
      color:
        executionState === "SIGNAL_READY"
          ? "var(--accent)"
          : executionState === "EXECUTING"
            ? "var(--green)"
            : executionState === "SCANNING"
              ? "var(--blue)"
              : "var(--text-muted)",
      pulse: executionState === "EXECUTING",
    },
    {
      label: "OPEN TRADES",
      value: String(openTradeCount),
      color: openTradeCount > 0 ? "var(--green)" : "var(--text-muted)",
      pulse: false,
    },
    {
      label: "SYSTEM MODE",
      value: degraded ? "DEGRADED" : "NORMAL",
      color: degraded ? "var(--yellow)" : "var(--green)",
      pulse: degraded,
    },
  ];

  return (
    <div
      style={{
        display: "flex",
        alignItems: "stretch",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border-default)",
        overflow: "hidden",
        background: "var(--bg-panel)",
      }}
      role="status"
      aria-label="System status strip"
    >
      {items.map((item, i) => (
        <div
          key={item.label}
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 3,
            padding: "9px 16px",
            borderRight:
              i < items.length - 1 ? "1px solid var(--border-default)" : "none",
            flex: 1,
            minWidth: 0,
          }}
        >
          <span
            className="num"
            style={{
              fontSize: 8,
              letterSpacing: "0.10em",
              color: "var(--text-faint)",
              fontWeight: 700,
              whiteSpace: "nowrap",
            }}
          >
            {item.label}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            {item.pulse && (
              <span
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: item.color,
                  animation: "pulse-dot 1.5s ease-in-out infinite",
                  flexShrink: 0,
                }}
                aria-hidden="true"
              />
            )}
            <span
              className="num"
              style={{
                fontSize: 10,
                fontWeight: 800,
                color: item.color,
                letterSpacing: "0.04em",
                whiteSpace: "nowrap",
              }}
            >
              {item.value}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
