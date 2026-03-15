"use client";

// ============================================================
// TUYUL FX Wolf-15 — SystemHealthCluster
// PRD: Command Center right column — system health panel
// Shows: status, redis, mt5, active_pairs, version, uptime
// ============================================================

import type { SystemHealth } from "@/types";

interface SystemHealthClusterProps {
  health: SystemHealth | undefined;
  isLoading?: boolean;
  wsStatus: string;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: ok ? "var(--green)" : "var(--red)",
        boxShadow: ok ? "0 0 6px rgba(0,230,118,0.6)" : "none",
        animation: ok ? "pulse-dot 2s ease-in-out infinite" : "none",
        flexShrink: 0,
      }}
      aria-hidden="true"
    />
  );
}

function Row({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: React.ReactNode;
  valueColor?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        fontSize: 11,
        gap: 8,
      }}
    >
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontWeight: 700,
          color: valueColor ?? "var(--text-secondary)",
          textAlign: "right",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export default function SystemHealthCluster({
  health,
  isLoading,
  wsStatus,
}: SystemHealthClusterProps) {
  const isHealthy = health?.status === "ok";

  return (
    <div
      className="panel"
      style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
        }}
      >
        <StatusDot ok={isHealthy && !isLoading} />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: "var(--text-muted)",
          }}
        >
          SYSTEM HEALTH
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 800,
            color: isHealthy ? "var(--green)" : isLoading ? "var(--text-faint)" : "var(--red)",
            letterSpacing: "0.06em",
          }}
        >
          {isLoading ? "CHECKING..." : (health?.status?.toUpperCase() ?? "UNKNOWN")}
        </span>
      </div>

      {/* Divider */}
      <div style={{ borderTop: "1px solid var(--border-default)" }} />

      {/* Service rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {health?.redis_connected !== undefined && (
          <Row
            label="Redis"
            value={health.redis_connected ? "CONNECTED" : "DISCONNECTED"}
            valueColor={health.redis_connected ? "var(--green)" : "var(--red)"}
          />
        )}
        {health?.mt5_connected !== undefined && (
          <Row
            label="MT5 Bridge"
            value={health.mt5_connected ? "CONNECTED" : "DISCONNECTED"}
            valueColor={health.mt5_connected ? "var(--green)" : "var(--red)"}
          />
        )}
        <Row
          label="Live Feed"
          value={wsStatus}
          valueColor={
            wsStatus === "CONNECTED"
              ? "var(--green)"
              : wsStatus === "RECONNECTING"
              ? "var(--yellow)"
              : "var(--red)"
          }
        />
        {health?.active_pairs !== undefined && (
          <Row
            label="Active Pairs"
            value={health.active_pairs}
            valueColor="var(--text-primary)"
          />
        )}
        {health?.active_trades !== undefined && (
          <Row
            label="Active Trades"
            value={health.active_trades}
            valueColor={health.active_trades > 0 ? "var(--green)" : "var(--text-muted)"}
          />
        )}
        {health?.uptime_seconds !== undefined && (
          <Row
            label="Uptime"
            value={formatUptime(health.uptime_seconds)}
            valueColor="var(--text-muted)"
          />
        )}
        {health?.version && (
          <Row
            label="Version"
            value={health.version}
            valueColor="var(--text-faint)"
          />
        )}
        {health?.last_verdict_at && (
          <Row
            label="Last Verdict"
            value={new Date(health.last_verdict_at * 1000).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })}
            valueColor="var(--text-muted)"
          />
        )}
      </div>
    </div>
  );
}
