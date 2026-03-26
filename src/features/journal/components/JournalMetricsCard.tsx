"use client";

import type { JournalMetrics } from "@/types";

function MetricRow({
    label,
    value,
    color = "var(--text-primary)",
}: {
    label: string;
    value: string | number;
    color?: string;
}) {
    return (
        <div
            style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                fontSize: 11,
            }}
        >
            <span style={{ color: "var(--text-muted)" }}>{label}</span>
            <span className="num" style={{ fontWeight: 600, color }}>
                {value}
            </span>
        </div>
    );
}

interface JournalMetricsCardProps {
    metrics: JournalMetrics;
}

export function JournalMetricsCard({ metrics }: JournalMetricsCardProps) {
    const wrColor =
        metrics.win_rate >= 0.6
            ? "var(--green)"
            : metrics.win_rate >= 0.4
                ? "var(--yellow)"
                : "var(--red)";

    return (
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div
                style={{
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.1em",
                    color: "var(--text-muted)",
                }}
            >
                JOURNAL METRICS
            </div>

            {/* Win rate gauge */}
            <div style={{ textAlign: "center", padding: "10px 0" }}>
                <div
                    className="num"
                    style={{
                        fontSize: 32,
                        fontWeight: 700,
                        color: wrColor,
                        lineHeight: 1,
                    }}
                >
                    {Math.round(metrics.win_rate * 100)}%
                </div>
                <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
                    WIN RATE
                </div>
            </div>

            <div className="progress-bar">
                <div
                    className="progress-fill"
                    style={{
                        width: `${metrics.win_rate * 100}%`,
                        background: wrColor,
                    }}
                />
            </div>

            {/* Stats */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <MetricRow label="Total Trades" value={metrics.total_trades} />
                <MetricRow
                    label="Wins / Losses"
                    value={`${metrics.total_wins} / ${metrics.total_losses}`}
                />
                <MetricRow
                    label="Total PnL"
                    value={`${metrics.total_pnl >= 0 ? "+" : ""}${metrics.total_pnl.toFixed(2)}`}
                    color={metrics.total_pnl >= 0 ? "var(--green)" : "var(--red)"}
                />
                <MetricRow
                    label="Avg RR"
                    value={metrics.avg_rr.toFixed(2)}
                    color="var(--accent)"
                />
                <MetricRow
                    label="Rejection Rate"
                    value={`${Math.round(metrics.rejection_rate * 100)}%`}
                />
                {metrics.profit_factor !== undefined && (
                    <MetricRow
                        label="Profit Factor"
                        value={metrics.profit_factor.toFixed(2)}
                        color={metrics.profit_factor >= 1.5 ? "var(--green)" : "var(--yellow)"}
                    />
                )}
                {metrics.expectancy !== undefined && (
                    <MetricRow
                        label="Expectancy"
                        value={metrics.expectancy.toFixed(2)}
                        color={metrics.expectancy > 0 ? "var(--green)" : "var(--red)"}
                    />
                )}
                {metrics.best_pair && (
                    <MetricRow label="Best Pair" value={metrics.best_pair} color="var(--green)" />
                )}
                {metrics.worst_pair && (
                    <MetricRow label="Worst Pair" value={metrics.worst_pair} color="var(--red)" />
                )}
            </div>
        </div>
    );
}
