"use client";

import type { EAAgent } from "@/types";

interface Props {
    agent: EAAgent | null;
}

function formatTimestamp(iso: string): string {
    if (!iso) return "—";
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
    }
}

export function AgentDetailPanel({ agent }: Props) {
    if (!agent) {
        return (
            <div
                style={{
                    padding: 20,
                    textAlign: "center",
                    color: "var(--text-muted)",
                    fontSize: 12,
                }}
            >
                Select an agent to view details
            </div>
        );
    }

    const rows: Array<{ label: string; value: string; color?: string }> = [
        { label: "Agent ID", value: agent.agent_id },
        { label: "Account", value: agent.account_id || "—" },
        { label: "Profile", value: agent.profile },
        { label: "Scope", value: agent.scope },
        { label: "Version", value: `v${agent.version}` },
        {
            label: "Status",
            value: agent.status.toUpperCase(),
            color: agent.healthy ? "var(--green)" : "var(--red)",
        },
        { label: "Trades Executed", value: String(agent.trades_executed) },
        {
            label: "Trades Failed",
            value: String(agent.trades_failed),
            color: agent.trades_failed > 0 ? "var(--red)" : undefined,
        },
        { label: "Last Heartbeat", value: formatTimestamp(agent.last_heartbeat) },
        { label: "Last Success", value: formatTimestamp(agent.last_success) },
        { label: "Last Failure", value: formatTimestamp(agent.last_failure) },
    ];

    if (agent.failure_reason) {
        rows.push({
            label: "Failure Reason",
            value: agent.failure_reason,
            color: "var(--red)",
        });
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div
                style={{
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    color: "var(--text-muted)",
                    paddingBottom: 4,
                    borderBottom: "1px solid var(--bg-border)",
                }}
            >
                AGENT DETAIL — {agent.agent_id}
            </div>

            {rows.map((row) => (
                <div
                    key={row.label}
                    style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}
                >
                    <span style={{ color: "var(--text-muted)" }}>{row.label}</span>
                    <span
                        className="num"
                        style={{ fontWeight: 600, color: row.color ?? "var(--text-secondary)" }}
                    >
                        {row.value}
                    </span>
                </div>
            ))}
        </div>
    );
}
