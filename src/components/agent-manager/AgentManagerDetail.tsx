"use client";

import type { AgentItem } from "@/types/agent-manager";
import { AgentStatus } from "@/types/agent-manager";
import { formatDate } from "@/lib/formatters";

interface Props {
  agent: AgentItem | null;
}

const STATUS_COLORS: Record<AgentStatus, string> = {
  [AgentStatus.ONLINE]: "var(--green)",
  [AgentStatus.WARNING]: "var(--amber, #f59e0b)",
  [AgentStatus.OFFLINE]: "var(--red)",
  [AgentStatus.QUARANTINED]: "var(--purple, #a855f7)",
  [AgentStatus.DISABLED]: "var(--text-muted)",
};

function fmt(val: string | null | undefined): string {
  if (!val) return "—";
  return formatDate(val);
}

function fmtUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function AgentManagerDetail({ agent }: Props) {
  if (!agent) {
    return (
      <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
        Select an agent to view details
      </div>
    );
  }

  const statusColor = STATUS_COLORS[agent.status] ?? "var(--text-muted)";
  const rt = agent.runtime;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SectionHeader title={`AGENT — ${agent.agent_name}`} />
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Row label="ID" value={agent.id} />
        <Row label="Name" value={agent.agent_name} />
        <Row label="EA Class" value={agent.ea_class} />
        <Row label="Subtype" value={agent.ea_subtype} />
        <Row label="Execution Mode" value={agent.execution_mode} />
        <Row label="Reporter Mode" value={agent.reporter_mode} />
        <Row label="Status" value={agent.status} color={statusColor} />
      </div>

      <SectionHeader title="MT5 CONNECTION" />
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Row label="MT5 Login" value={agent.mt5_login !== null ? String(agent.mt5_login) : "—"} />
        <Row label="MT5 Server" value={agent.mt5_server ?? "—"} />
        <Row label="Broker" value={agent.broker_name ?? "—"} />
        <Row label="Linked Account" value={agent.linked_account_id ?? "—"} />
        <Row label="Linked Profile" value={agent.linked_profile_id ?? "—"} />
      </div>

      <SectionHeader title="STRATEGY" />
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Row label="Strategy Profile" value={agent.strategy_profile || "—"} />
        <Row label="Risk Multiplier" value={String(agent.risk_multiplier)} />
        <Row label="News Lock Setting" value={agent.news_lock_setting || "—"} />
        <Row label="Safe Mode" value={agent.safe_mode ? "ENABLED" : "OFF"} color={agent.safe_mode ? "var(--amber, #f59e0b)" : "var(--green)"} />
        <Row label="Locked" value={agent.locked ? "YES" : "NO"} color={agent.locked ? "var(--amber, #f59e0b)" : "var(--text-secondary)"} />
        {agent.locked && (
          <>
            <Row label="Lock Reason" value={agent.lock_reason ?? "—"} color="var(--amber, #f59e0b)" />
            <Row label="Locked By" value={agent.locked_by ?? "—"} />
            <Row label="Locked At" value={fmt(agent.locked_at)} />
          </>
        )}
      </div>

      {rt && (
        <>
          <SectionHeader title="RUNTIME" />
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Row label="Trades Executed" value={String(rt.trades_executed)} valueColor="var(--green)" />
            <Row label="Trades Failed" value={String(rt.trades_failed)} color={rt.trades_failed > 0 ? "var(--red)" : undefined} />
            <Row label="Uptime" value={fmtUptime(rt.uptime_seconds)} />
            <Row label="Last Heartbeat" value={fmt(rt.last_heartbeat)} />
            <Row label="Last Success" value={fmt(rt.last_success)} />
            <Row label="Last Failure" value={fmt(rt.last_failure)} />
            {rt.failure_reason && <Row label="Failure Reason" value={rt.failure_reason} color="var(--red)" />}
            {rt.cpu_usage_pct !== null && <Row label="CPU Usage" value={`${rt.cpu_usage_pct?.toFixed(1)}%`} />}
            {rt.memory_mb !== null && <Row label="Memory" value={`${rt.memory_mb?.toFixed(0)} MB`} />}
            {rt.connection_latency_ms !== null && <Row label="Latency" value={`${rt.connection_latency_ms?.toFixed(0)} ms`} />}
          </div>
        </>
      )}

      <SectionHeader title="METADATA" />
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {agent.version && <Row label="Version" value={`v${agent.version}`} />}
        {agent.notes && <Row label="Notes" value={agent.notes} />}
        <Row label="Created" value={fmt(agent.created_at)} />
        <Row label="Updated" value={fmt(agent.updated_at)} />
      </div>
    </div>
  );
}

function SectionHeader({ title }: { title: string }) {
  return (
    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)", paddingBottom: 4, borderBottom: "1px solid var(--bg-border)" }}>
      {title}
    </div>
  );
}

function Row({ label, value, color, valueColor }: { label: string; value: string; color?: string; valueColor?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span className="num" style={{ fontWeight: 600, color: color ?? valueColor ?? "var(--text-secondary)" }}>{value}</span>
    </div>
  );
}
