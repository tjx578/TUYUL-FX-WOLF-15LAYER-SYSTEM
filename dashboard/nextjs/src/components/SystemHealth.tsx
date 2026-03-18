"use client";

// ============================================================
// TUYUL FX Wolf-15 — SystemHealth widget
// ============================================================

import { useHealth } from "@/lib/api";
import type { FeedStatus } from "@/types";

const FEED_STATUS_COLOR: Record<FeedStatus, string> = {
  fresh: "var(--green)",
  stale_preserved: "var(--yellow)",
  no_producer: "#ff9f0a",
  no_transport: "var(--red)",
  config_error: "var(--red)",
};

function formatFeedStatus(status?: FeedStatus): string {
  return status ? status.toUpperCase() : "UNKNOWN";
}

export function SystemHealth() {
  const { data: health, isLoading } = useHealth();

  const isHealthy = health?.status === "ok";
  const statusColor = isHealthy ? "var(--green)" : "var(--red)";
  const feedStatus = health?.feed_status;
  const feedColor = feedStatus ? FEED_STATUS_COLOR[feedStatus] : "var(--text-muted)";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        background: "var(--bg-card)",
        border: `1px solid var(--bg-border)`,
        borderRadius: 6,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.1em",
          color: "var(--text-muted)",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        SYSTEM
        <span
          className="live-dot"
          style={{
            background: isHealthy ? "var(--green)" : "var(--red)",
            animation: isHealthy ? "pulse-dot 1.5s ease-in-out infinite" : "none",
          }}
        />
      </div>

      {isLoading ? (
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          Checking...
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
            <span style={{ color: "var(--text-muted)" }}>Status</span>
            <span style={{ color: statusColor, fontWeight: 600 }}>
              {health?.status?.toUpperCase() ?? "UNKNOWN"}
            </span>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, gap: 12 }}>
            <span style={{ color: "var(--text-muted)" }}>Feed</span>
            <span style={{ color: feedColor, fontWeight: 600, textAlign: "right" }}>
              {formatFeedStatus(feedStatus)}
            </span>
          </div>

          {health?.feed_staleness_seconds !== undefined && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, gap: 12 }}>
              <span style={{ color: "var(--text-muted)" }}>Last Seen</span>
              <span className="num" style={{ color: "var(--text-secondary)", textAlign: "right" }}>
                {Number.isFinite(health.feed_staleness_seconds)
                  ? `${Math.round(health.feed_staleness_seconds)}s ago`
                  : "N/A"}
              </span>
            </div>
          )}

          {health?.redis_connected !== undefined && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
              <span style={{ color: "var(--text-muted)" }}>Redis</span>
              <span style={{ color: health.redis_connected ? "var(--green)" : "var(--red)" }}>
                {health.redis_connected ? "CONNECTED" : "DISCONNECTED"}
              </span>
            </div>
          )}

          {health?.mt5_connected !== undefined && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
              <span style={{ color: "var(--text-muted)" }}>MT5</span>
              <span style={{ color: health.mt5_connected ? "var(--green)" : "var(--red)" }}>
                {health.mt5_connected ? "CONNECTED" : "DISCONNECTED"}
              </span>
            </div>
          )}

          {health?.active_pairs !== undefined && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
              <span style={{ color: "var(--text-muted)" }}>Pairs</span>
              <span className="num" style={{ color: "var(--text-secondary)" }}>
                {health.active_pairs}
              </span>
            </div>
          )}

          {health?.version && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
              <span style={{ color: "var(--text-muted)" }}>Version</span>
              <span
                className="num"
                style={{ color: "var(--text-muted)", fontSize: 10 }}
              >
                {health.version}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Keep default export for backward compat
export default SystemHealth;
