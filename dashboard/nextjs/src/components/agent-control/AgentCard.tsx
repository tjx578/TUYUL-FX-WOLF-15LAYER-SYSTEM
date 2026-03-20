"use client";

import type { EAAgent } from "@/types";

interface Props {
    agent: EAAgent;
    selected: boolean;
    onSelect: (id: string) => void;
}

const STATUS_STYLES: Record<string, { color: string; bg: string; border: string; label: string }> = {
    connected: {
        color: "var(--green)",
        bg: "rgba(16, 185, 129, 0.08)",
        border: "rgba(16, 185, 129, 0.2)",
        label: "CONNECTED",
    },
    disconnected: {
        color: "var(--red)",
        bg: "rgba(239, 68, 68, 0.08)",
        border: "rgba(239, 68, 68, 0.2)",
        label: "DISCONNECTED",
    },
    degraded: {
        color: "var(--amber, #f59e0b)",
        bg: "rgba(245, 158, 11, 0.08)",
        border: "rgba(245, 158, 11, 0.2)",
        label: "DEGRADED",
    },
    cooldown: {
        color: "var(--cyan, #06b6d4)",
        bg: "rgba(6, 182, 212, 0.08)",
        border: "rgba(6, 182, 212, 0.2)",
        label: "COOLDOWN",
    },
};

function formatUptime(seconds: number): string {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${m}m`;
}

function formatTimeAgo(iso: string): string {
    if (!iso) return "—";
    const diff = Date.now() - new Date(iso).getTime();
    if (diff < 0) return "just now";
    const secs = Math.floor(diff / 1000);
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    return `${Math.floor(secs / 3600)}h ago`;
}

export function AgentCard({ agent, selected, onSelect }: Props) {
    const style = STATUS_STYLES[agent.status] ?? STATUS_STYLES.disconnected;

    return (
        <div
            onClick={() => onSelect(agent.agent_id)}
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
                    {agent.agent_id}
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
                    }}
                >
                    {style.label}
                </span>
            </div>

            {/* Metrics */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                <MetricRow label="Profile" value={agent.profile} />
                <MetricRow label="Uptime" value={formatUptime(agent.uptime_seconds)} />
                <MetricRow label="Executed" value={String(agent.trades_executed)} valueColor="var(--green)" />
                <MetricRow label="Failed" value={String(agent.trades_failed)} valueColor={agent.trades_failed > 0 ? "var(--red)" : "var(--text-secondary)"} />
            </div>

            {/* Last activity */}
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-muted)" }}>
                <span>Last OK: {formatTimeAgo(agent.last_success)}</span>
                <span>v{agent.version}</span>
            </div>
        </div>
    );
}

function MetricRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
    return (
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
            <span style={{ color: "var(--text-muted)" }}>{label}</span>
            <span className="num" style={{ fontWeight: 600, color: valueColor ?? "var(--text-secondary)" }}>
                {value}
            </span>
        </div>
    );
}
