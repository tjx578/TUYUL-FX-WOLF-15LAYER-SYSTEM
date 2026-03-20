"use client";

import type { AgentHealthSummary } from "@/hooks/useAgentControlState";

interface Props {
    summary: AgentHealthSummary;
    safeMode: boolean;
    queueDepth: number;
    queueMax: number;
}

const STATUS_COLORS: Record<AgentHealthSummary["overallStatus"], string> = {
    healthy: "var(--green)",
    degraded: "var(--amber, #f59e0b)",
    critical: "var(--red)",
    offline: "var(--text-muted)",
};

const STATUS_LABELS: Record<AgentHealthSummary["overallStatus"], string> = {
    healthy: "ALL CONNECTED",
    degraded: "PARTIALLY DEGRADED",
    critical: "CRITICAL",
    offline: "OFFLINE",
};

export function AgentHealthOverview({ summary, safeMode, queueDepth, queueMax }: Props) {
    const statusColor = STATUS_COLORS[summary.overallStatus];

    return (
        <div
            style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: 12,
            }}
        >
            {/* Overall Status */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)" }}>
                    STATUS
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span
                        className="live-dot"
                        style={{
                            background: statusColor,
                            animation: summary.overallStatus === "healthy" ? "pulse-dot 1.5s ease-in-out infinite" : "none",
                        }}
                    />
                    <span style={{ fontSize: 13, fontWeight: 600, color: statusColor }}>
                        {STATUS_LABELS[summary.overallStatus]}
                    </span>
                </span>
            </div>

            {/* Agents Connected */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)" }}>
                    AGENTS
                </span>
                <span className="num" style={{ fontSize: 20, fontWeight: 700, color: "var(--text-primary)" }}>
                    {summary.connectedAgents}
                    <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 400 }}>
                        {" "}/ {summary.totalAgents}
                    </span>
                </span>
            </div>

            {/* Health % */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)" }}>
                    HEALTH
                </span>
                <span className="num" style={{ fontSize: 20, fontWeight: 700, color: statusColor }}>
                    {summary.healthPercent}%
                </span>
            </div>

            {/* Queue */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)" }}>
                    QUEUE
                </span>
                <span className="num" style={{ fontSize: 20, fontWeight: 700, color: "var(--text-secondary)" }}>
                    {queueDepth}
                    <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 400 }}>
                        {" "}/ {queueMax}
                    </span>
                </span>
            </div>

            {/* Safe Mode */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)" }}>
                    SAFE MODE
                </span>
                <span
                    style={{
                        fontSize: 13,
                        fontWeight: 600,
                        color: safeMode ? "var(--amber, #f59e0b)" : "var(--green)",
                    }}
                >
                    {safeMode ? "ENABLED" : "OFF"}
                </span>
            </div>
        </div>
    );
}
