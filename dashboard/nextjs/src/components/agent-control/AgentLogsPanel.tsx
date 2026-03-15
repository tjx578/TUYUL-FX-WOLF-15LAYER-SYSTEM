"use client";

import type { EALog } from "@/types";

interface Props {
    logs: EALog[] | undefined;
    isLoading?: boolean;
}

const LEVEL_COLORS: Record<string, string> = {
    INFO: "var(--cyan, #06b6d4)",
    WARNING: "var(--amber, #f59e0b)",
    ERROR: "var(--red)",
    DEBUG: "var(--text-muted)",
};

export function AgentLogsPanel({ logs, isLoading }: Props) {
    if (isLoading) {
        return (
            <div style={{ padding: 12, color: "var(--text-muted)", fontSize: 11 }}>
                Loading logs...
            </div>
        );
    }

    if (!logs || logs.length === 0) {
        return (
            <div style={{ padding: 12, color: "var(--text-muted)", fontSize: 11, textAlign: "center" }}>
                No log entries.
            </div>
        );
    }

    return (
        <div
            style={{
                maxHeight: 260,
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: 2,
                fontFamily: "var(--font-mono, monospace)",
                fontSize: 11,
            }}
        >
            {logs.map((log) => (
                <div
                    key={log.id}
                    style={{
                        display: "flex",
                        gap: 8,
                        padding: "3px 4px",
                        borderBottom: "1px solid rgba(255,255,255,0.03)",
                        lineHeight: 1.4,
                    }}
                >
                    <span style={{ color: "var(--text-muted)", flexShrink: 0, minWidth: 60 }}>
                        {formatLogTime(log.timestamp)}
                    </span>
                    <span
                        style={{
                            color: LEVEL_COLORS[log.level] ?? "var(--text-muted)",
                            fontWeight: 600,
                            flexShrink: 0,
                            minWidth: 48,
                        }}
                    >
                        {log.level}
                    </span>
                    {log.agent_id && (
                        <span style={{ color: "var(--text-muted)", flexShrink: 0 }}>
                            [{log.agent_id}]
                        </span>
                    )}
                    <span style={{ color: "var(--text-secondary)", wordBreak: "break-word" }}>
                        {log.message}
                    </span>
                </div>
            ))}
        </div>
    );
}

function formatLogTime(iso: string): string {
    try {
        return new Date(iso).toLocaleTimeString(undefined, { hour12: false });
    } catch {
        return iso;
    }
}
