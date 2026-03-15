"use client";

import React from "react";

// ── TradeStatusBadge ─────────────────────────────────────────

const STATUS_STYLES: Record<string, { bg: string; color: string; border: string }> = {
    OPEN: { bg: "var(--green-glow)", color: "var(--green)", border: "var(--border-success)" },
    PENDING: { bg: "var(--yellow-glow, rgba(255,200,0,0.08))", color: "var(--yellow, #ffc800)", border: "var(--border-warning, rgba(255,200,0,0.25))" },
    INTENDED: { bg: "var(--blue-glow, rgba(56,189,248,0.08))", color: "var(--blue, #38bdf8)", border: "var(--border-info, rgba(56,189,248,0.25))" },
    CLOSED: { bg: "var(--bg-elevated)", color: "var(--text-muted)", border: "var(--border-subtle)" },
    CANCELLED: { bg: "var(--bg-elevated)", color: "var(--text-muted)", border: "var(--border-subtle)" },
    SKIPPED: { bg: "var(--bg-elevated)", color: "var(--text-muted)", border: "var(--border-subtle)" },
};

export function TradeStatusBadge({ status }: { status?: string }) {
    const style = STATUS_STYLES[status ?? ""] ?? STATUS_STYLES.CLOSED;
    return (
        <span
            style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.06em",
                padding: "2px 8px",
                borderRadius: 4,
                background: style.bg,
                color: style.color,
                border: `1px solid ${style.border}`,
                fontFamily: "var(--font-mono)",
                textTransform: "uppercase",
            }}
        >
            {status ?? "—"}
        </span>
    );
}

// ── ExecutionAnomalyBanner ───────────────────────────────────

interface AnomalyItem {
    trade_id: string;
    anomalies: Array<{ type: string; message: string; severity: string }>;
}

export function ExecutionAnomalyBanner({ anomalies }: { anomalies: AnomalyItem[] }) {
    if (!anomalies.length) return null;

    const totalCount = anomalies.reduce((sum, a) => sum + a.anomalies.length, 0);
    const hasCritical = anomalies.some((a) => a.anomalies.some((x) => x.severity === "CRITICAL"));

    return (
        <div
            data-testid="anomaly-banner"
            style={{
                background: hasCritical ? "var(--red-glow, rgba(255,77,79,0.08))" : "var(--yellow-glow, rgba(255,200,0,0.06))",
                border: `1px solid ${hasCritical ? "var(--border-danger)" : "var(--border-warning, rgba(255,200,0,0.25))"}`,
                borderRadius: "var(--radius-md, 8px)",
                padding: "10px 14px",
                display: "flex",
                alignItems: "center",
                gap: 10,
            }}
        >
            <span style={{ fontSize: 16 }}>{hasCritical ? "⚠" : "⚡"}</span>
            <div>
                <div
                    style={{
                        fontSize: 11,
                        fontWeight: 700,
                        color: hasCritical ? "var(--red)" : "var(--yellow, #ffc800)",
                        fontFamily: "var(--font-mono)",
                        letterSpacing: "0.06em",
                    }}
                >
                    {totalCount} EXECUTION {totalCount === 1 ? "ANOMALY" : "ANOMALIES"} DETECTED
                </div>
                <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
                    {anomalies
                        .flatMap((a) => a.anomalies.map((x) => `${a.trade_id.slice(0, 8)}: ${x.message}`))
                        .slice(0, 3)
                        .join(" · ")}
                    {totalCount > 3 && ` (+${totalCount - 3} more)`}
                </div>
            </div>
        </div>
    );
}

// ── SyncMismatchIndicator ────────────────────────────────────

export function SyncMismatchIndicator({ flags }: { flags: string[] }) {
    if (!flags.length) return null;
    return (
        <span
            title={flags.join(", ")}
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 3,
                fontSize: 9,
                fontWeight: 600,
                color: "var(--red)",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.04em",
            }}
        >
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--red)", display: "inline-block" }} />
            MISMATCH
        </span>
    );
}
