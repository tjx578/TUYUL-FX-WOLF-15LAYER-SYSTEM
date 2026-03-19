"use client";

// ============================================================
// TUYUL FX Wolf-15 — SystemHealth widget
// ============================================================

import { useHealth } from "@/lib/api";
import { useOrchestratorState } from "@/lib/api";
import type { FeedStatus, FreshnessClassLabel } from "@/types";

/** Map backend internal feed_status to the approved FreshnessClass label. */
const toFreshnessLabel = (
  feedStatus?: FeedStatus,
  staleness?: number,
): FreshnessClassLabel => {
  if (!feedStatus) return "LIVE";
  if (feedStatus === "config_error") return "CONFIG_ERROR";
  if (feedStatus === "no_transport") return "NO_TRANSPORT";
  if (feedStatus === "no_producer") return "NO_PRODUCER";
  if (feedStatus === "stale_preserved") return "STALE_PRESERVED";
  // "fresh" — split by staleness age: ≤30s = LIVE, else DEGRADED_BUT_REFRESHING
  if (staleness !== undefined && staleness > 30) return "DEGRADED_BUT_REFRESHING";
  return "LIVE";
};

const FRESHNESS_COLOR: Record<FreshnessClassLabel, string> = {
  LIVE: "var(--green)",
  DEGRADED_BUT_REFRESHING: "var(--yellow)",
  STALE_PRESERVED: "#ff9f0a",
  NO_PRODUCER: "var(--red)",
  NO_TRANSPORT: "var(--red)",
  CONFIG_ERROR: "var(--red)",
};

const FRESHNESS_DISPLAY: Record<FreshnessClassLabel, string> = {
  LIVE: "LIVE",
  DEGRADED_BUT_REFRESHING: "DEGRADED",
  STALE_PRESERVED: "STALE",
  NO_PRODUCER: "NO PRODUCER",
  NO_TRANSPORT: "NO TRANSPORT",
  CONFIG_ERROR: "CONFIG ERROR",
};

export function SystemHealth() {
  const { data: health, isLoading } = useHealth();
  const { data: orchestrator } = useOrchestratorState();

  const isHealthy = health?.status === "ok";
  const statusColor = isHealthy ? "var(--green)" : "var(--red)";
  const freshnessLabel = toFreshnessLabel(health?.feed_status, health?.feed_staleness_seconds);
  const feedColor = FRESHNESS_COLOR[freshnessLabel];

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
              {FRESHNESS_DISPLAY[freshnessLabel]}
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

          {health?.producer_heartbeat_age_seconds !== undefined && health.producer_heartbeat_age_seconds !== null && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, gap: 12 }}>
              <span style={{ color: "var(--text-muted)" }}>Heartbeat</span>
              <span
                className="num"
                style={{
                  color: health.producer_alive ? "var(--green)" : "var(--red)",
                  textAlign: "right",
                }}
              >
                {`${Math.round(health.producer_heartbeat_age_seconds)}s ago`}
              </span>
            </div>
          )}

          {orchestrator?.orchestrator_ready !== undefined && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, gap: 12 }}>
              <span style={{ color: "var(--text-muted)" }}>Orchestrator</span>
              <span
                className="num"
                style={{
                  color: orchestrator.orchestrator_ready ? "var(--green)" : "var(--red)",
                  textAlign: "right",
                }}
              >
                {orchestrator.orchestrator_ready ? "READY" : (orchestrator.mode ?? "NOT_READY")}
              </span>
            </div>
          )}

          {orchestrator?.orchestrator_heartbeat_age_seconds !== undefined &&
            orchestrator?.orchestrator_heartbeat_age_seconds !== null && (
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, gap: 12 }}>
                <span style={{ color: "var(--text-muted)" }}>Orch HB</span>
                <span
                  className="num"
                  style={{
                    color: orchestrator.orchestrator_ready ? "var(--green)" : "var(--yellow)",
                    textAlign: "right",
                  }}
                >
                  {`${Math.round(orchestrator.orchestrator_heartbeat_age_seconds)}s ago`}
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
