"use client";

import type { AgentItem } from "@/types/agent-manager";
import { AgentStatus } from "@/types/agent-manager";

interface Props {
  agent: AgentItem;
  selected: boolean;
  onSelect: (id: string) => void;
}

const STATUS_STYLES: Record<AgentStatus, { color: string; bg: string; border: string; label: string; pulse: boolean }> = {
  [AgentStatus.ONLINE]: {
    color: "var(--green)",
    bg: "rgba(16, 185, 129, 0.08)",
    border: "rgba(16, 185, 129, 0.2)",
    label: "ONLINE",
    pulse: true,
  },
  [AgentStatus.WARNING]: {
    color: "var(--amber, #f59e0b)",
    bg: "rgba(245, 158, 11, 0.08)",
    border: "rgba(245, 158, 11, 0.2)",
    label: "WARNING",
    pulse: false,
  },
  [AgentStatus.OFFLINE]: {
    color: "var(--red)",
    bg: "rgba(239, 68, 68, 0.08)",
    border: "rgba(239, 68, 68, 0.2)",
    label: "OFFLINE",
    pulse: false,
  },
  [AgentStatus.QUARANTINED]: {
    color: "var(--purple, #a855f7)",
    bg: "rgba(168, 85, 247, 0.08)",
    border: "rgba(168, 85, 247, 0.2)",
    label: "QUARANTINED",
    pulse: false,
  },
  [AgentStatus.DISABLED]: {
    color: "var(--text-muted)",
    bg: "rgba(100, 116, 139, 0.08)",
    border: "rgba(100, 116, 139, 0.2)",
    label: "DISABLED",
    pulse: false,
  },
};

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function formatTimeAgo(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return "just now";
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

export function AgentManagerCard({ agent, selected, onSelect }: Props) {
  const style = STATUS_STYLES[agent.status] ?? STATUS_STYLES[AgentStatus.OFFLINE];

  return (
    <div
      onClick={() => onSelect(agent.id)}
      style={{
        padding: 16,
        borderRadius: 12,
        border: selected
          ? "1.5px solid var(--cyan, #06b6d4)"
          : "1px solid var(--bg-border)",
        background: selected ? "rgba(6, 182, 212, 0.04)" : "var(--bg-card)",
        cursor: "pointer",
        transition: "all 0.2s ease",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
          {agent.agent_name}
        </span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "0.05em",
            padding: "2px 8px",
            borderRadius: 9999,
            color: style.color,
            background: style.bg,
            border: `1px solid ${style.border}`,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          {style.pulse && (
            <span
              className="live-dot"
              style={{
                background: style.color,
                animation: "pulse-dot 1.5s ease-in-out infinite",
                width: 6,
                height: 6,
              }}
            />
          )}
          {style.label}
        </span>
      </div>

      {/* Class + Subtype + Mode */}
      <div
        style={{
          display: "flex",
          gap: 6,
          flexWrap: "wrap",
        }}
      >
        <Tag value={agent.ea_class} />
        <Tag value={agent.ea_subtype} />
        <Tag value={agent.execution_mode} />
      </div>

      {/* Runtime Metrics */}
      {agent.runtime && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
          <MetricRow
            label="Executed"
            value={String(agent.runtime.trades_executed)}
            valueColor="var(--green)"
          />
          <MetricRow
            label="Failed"
            value={String(agent.runtime.trades_failed)}
            valueColor={
              agent.runtime.trades_failed > 0 ? "var(--red)" : "var(--text-secondary)"
            }
          />
          <MetricRow label="Uptime" value={formatUptime(agent.runtime.uptime_seconds)} />
          <MetricRow
            label="Heartbeat"
            value={formatTimeAgo(agent.runtime.last_heartbeat)}
          />
        </div>
      )}

      {/* Broker + Footer */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "var(--text-muted)",
        }}
      >
        <span>{agent.broker_name ?? "—"}</span>
        <span style={{ display: "flex", gap: 6 }}>
          {agent.locked && (
            <span style={{ color: "var(--amber, #f59e0b)", fontWeight: 600 }}>LOCKED</span>
          )}
          {agent.safe_mode && (
            <span style={{ color: "var(--cyan, #06b6d4)", fontWeight: 600 }}>SAFE</span>
          )}
          {agent.version && <span>v{agent.version}</span>}
        </span>
      </div>
    </div>
  );
}

function MetricRow({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span
        className="num"
        style={{ fontWeight: 600, color: valueColor ?? "var(--text-secondary)" }}
      >
        {value}
      </span>
    </div>
  );
}

function Tag({ value }: { value: string }) {
  return (
    <span
      style={{
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: "0.06em",
        padding: "1px 6px",
        borderRadius: 4,
        background: "rgba(255,255,255,0.05)",
        color: "var(--text-muted)",
        border: "1px solid var(--bg-border)",
      }}
    >
      {value}
    </span>
  );
}
