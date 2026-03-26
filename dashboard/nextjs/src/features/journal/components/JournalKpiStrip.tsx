"use client";

import type { JournalMetrics } from "@/types";

function JournalKpi({ label, value, color }: { label: string; value: string | number; color?: string }) {
    return (
        <div className="card" style={{ padding: "11px 14px", display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--text-muted)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                {label}
            </div>
            <div className="num" style={{ fontSize: 20, fontWeight: 700, color: color ?? "var(--text-primary)" }}>
                {value}
            </div>
        </div>
    );
}

export function JournalKpiStrip({ metrics }: { metrics: JournalMetrics }) {
    return (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12 }}>
            <JournalKpi
                label="WIN RATE"
                value={`${Math.round(metrics.win_rate * 100)}%`}
                color={metrics.win_rate >= 0.6 ? "var(--green)" : metrics.win_rate >= 0.4 ? "var(--yellow)" : "var(--red)"}
            />
            <JournalKpi
                label="TOTAL PNL"
                value={`${metrics.total_pnl >= 0 ? "+" : ""}${metrics.total_pnl.toFixed(2)}`}
                color={metrics.total_pnl >= 0 ? "var(--green)" : "var(--red)"}
            />
            <JournalKpi
                label="AVG R:R"
                value={metrics.avg_rr?.toFixed(2) ?? "—"}
                color={metrics.avg_rr >= 2 ? "var(--green)" : metrics.avg_rr >= 1.5 ? "var(--accent)" : "var(--yellow)"}
            />
            <JournalKpi
                label="PROFIT FACTOR"
                value={metrics.profit_factor?.toFixed(2) ?? "—"}
                color={(metrics.profit_factor ?? 0) >= 1.5 ? "var(--green)" : "var(--yellow)"}
            />
        </div>
    );
}
