"use client";

import type { AgentManagerSummary } from "@/hooks/useAgentManagerState";

interface Props {
  summary: AgentManagerSummary;
}

export function AgentManagerSummary({ summary }: Props) {
  const healthColor =
    summary.healthPercent >= 80
      ? "var(--green)"
      : summary.healthPercent >= 50
      ? "var(--amber, #f59e0b)"
      : "var(--red)";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))",
        gap: 12,
      }}
    >
      <StatCell label="TOTAL" value={String(summary.total)} valueColor="var(--text-primary)" />
      <StatCell label="ONLINE" value={String(summary.online)} valueColor="var(--green)" dot />
      <StatCell label="WARNING" value={String(summary.warning)} valueColor="var(--amber, #f59e0b)" />
      <StatCell label="OFFLINE" value={String(summary.offline)} valueColor="var(--red)" />
      <StatCell label="QUARANTINED" value={String(summary.quarantined)} valueColor="var(--purple, #a855f7)" />
      <StatCell label="DISABLED" value={String(summary.disabled)} valueColor="var(--text-muted)" />
      <StatCell label="HEALTH" value={`${summary.healthPercent}%`} valueColor={healthColor} />
      <StatCell
        label="LOCKED"
        value={String(summary.locked)}
        valueColor={summary.locked > 0 ? "var(--amber, #f59e0b)" : "var(--text-muted)"}
      />
    </div>
  );
}

function StatCell({
  label,
  value,
  valueColor,
  dot,
}: {
  label: string;
  value: string;
  valueColor?: string;
  dot?: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)" }}>
        {label}
      </span>
      <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
        {dot && (
          <span
            className="live-dot"
            style={{ background: valueColor ?? "var(--green)", animation: "pulse-dot 1.5s ease-in-out infinite" }}
          />
        )}
        <span className="num" style={{ fontSize: 20, fontWeight: 700, color: valueColor ?? "var(--text-primary)" }}>
          {value}
        </span>
      </span>
    </div>
  );
}
