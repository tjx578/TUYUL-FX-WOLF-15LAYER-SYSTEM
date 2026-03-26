"use client";

import React, { useEffect, useState, useMemo } from "react";
import type { TradeDeskTrade, TimelineEvent, Anomaly } from "../model/tradeDeskSchema";
import { TradeDetailResponseSchema } from "../model/tradeDeskSchema";
import { TradeStatusBadge } from "./TradeStatusBadge";
import { bearerHeader } from "@/lib/auth";
import { formatDate } from "@/lib/formatters";

// ── ExecutionTimelineDrawer ──────────────────────────────────

function ExecutionTimelineDrawer({ timeline }: { timeline: TimelineEvent[] }) {
    if (!timeline.length) {
        return (
            <div style={{ fontSize: 11, color: "var(--text-muted)", padding: "8px 0" }}>
                No execution events recorded.
            </div>
        );
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 0, paddingLeft: 8 }}>
            {timeline.map((ev, i) => {
                const isLast = i === timeline.length - 1;
                const ts = typeof ev.timestamp === "number"
                    ? formatDate(ev.timestamp * 1000, { showTime: true, showSeconds: true })
                    : formatDate(ev.timestamp, { showTime: true, showSeconds: true });

                return (
                    <div key={i} style={{ display: "flex", gap: 10, minHeight: 36 }}>
                        {/* Timeline line + dot */}
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 16 }}>
                            <div
                                style={{
                                    width: 8,
                                    height: 8,
                                    borderRadius: "50%",
                                    background: isLast ? "var(--blue, #38bdf8)" : "var(--text-muted)",
                                    flexShrink: 0,
                                    marginTop: 4,
                                }}
                            />
                            {!isLast && (
                                <div
                                    style={{
                                        width: 1,
                                        flex: 1,
                                        background: "var(--border-subtle)",
                                        minHeight: 16,
                                    }}
                                />
                            )}
                        </div>
                        {/* Event content */}
                        <div style={{ flex: 1, paddingBottom: 8 }}>
                            <div
                                style={{
                                    fontSize: 10,
                                    fontWeight: 700,
                                    color: "var(--text-primary)",
                                    fontFamily: "var(--font-mono)",
                                    letterSpacing: "0.04em",
                                }}
                            >
                                {ev.event}
                            </div>
                            <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 1 }}>
                                {ts}
                                {ev.close_reason && ` · ${ev.close_reason}`}
                                {ev.pnl !== undefined && (
                                    <span style={{ color: ev.pnl >= 0 ? "var(--green)" : "var(--red)", fontWeight: 700, marginLeft: 6 }}>
                                        {ev.pnl >= 0 ? "+" : ""}{ev.pnl.toFixed(2)}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

// ── TradeDetailPanel ─────────────────────────────────────────

interface TradeDetailPanelProps {
    tradeId: string;
    onClose: () => void;
}

export function TradeDetailPanel({ tradeId, onClose }: TradeDetailPanelProps) {
    const [trade, setTrade] = useState<TradeDeskTrade | null>(null);
    const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
    const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;

        async function fetchDetail() {
            setLoading(true);
            try {
                const auth = bearerHeader();
                const res = await fetch(`/api/v1/trades/${encodeURIComponent(tradeId)}/detail`, {
                    credentials: "include",
                    headers: { ...(auth ? { Authorization: auth } : {}) },
                });
                if (!res.ok) return;
                const json = await res.json();
                const parsed = TradeDetailResponseSchema.safeParse(json);
                if (!cancelled && parsed.success) {
                    setTrade(parsed.data.trade);
                    setTimeline(parsed.data.timeline);
                    setAnomalies(parsed.data.anomalies);
                }
            } catch {
                // Fail silently
            } finally {
                if (!cancelled) setLoading(false);
            }
        }

        fetchDetail();
        return () => { cancelled = true; };
    }, [tradeId]);

    if (loading) {
        return (
            <div className="card" style={{ padding: 20 }}>
                <div className="skeleton" style={{ height: 200, borderRadius: "var(--radius-sm)" }} />
            </div>
        );
    }

    if (!trade) {
        return (
            <div className="card" style={{ padding: 20, textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
                Trade not found.
            </div>
        );
    }

    const pair = trade.pair ?? "—";
    const dir = trade.direction;

    return (
        <div
            className="card"
            data-testid="trade-detail-panel"
            style={{
                padding: 16,
                display: "flex",
                flexDirection: "column",
                gap: 16,
                borderLeft: "3px solid var(--blue, #38bdf8)",
            }}
        >
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                    <div style={{ fontSize: 13, fontWeight: 800, color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
                        {pair}{" "}
                        <span style={{ color: dir === "BUY" ? "var(--green)" : "var(--red)" }}>{dir}</span>
                    </div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)", marginTop: 2 }}>
                        {trade.trade_id}
                    </div>
                </div>
                <button
                    onClick={onClose}
                    style={{
                        background: "none",
                        border: "none",
                        color: "var(--text-muted)",
                        cursor: "pointer",
                        fontSize: 16,
                        padding: "2px 6px",
                    }}
                >
                    ✕
                </button>
            </div>

            {/* Status + key fields */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <DetailField label="STATUS" value={<TradeStatusBadge status={trade.status} />} />
                <DetailField label="ACCOUNT" value={trade.account_id?.slice(0, 12)} />
                <DetailField label="ENTRY" value={trade.entry_price?.toFixed(5)} />
                <DetailField label="LOT" value={trade.lot_size?.toFixed(2)} />
                <DetailField label="STOP LOSS" value={trade.stop_loss?.toFixed(5)} color="var(--red)" />
                <DetailField label="TAKE PROFIT" value={trade.take_profit?.toFixed(5)} color="var(--green)" />
                {trade.pnl !== undefined && (
                    <DetailField
                        label="PNL"
                        value={`${trade.pnl >= 0 ? "+" : ""}${trade.pnl.toFixed(2)}`}
                        color={trade.pnl >= 0 ? "var(--green)" : "var(--red)"}
                    />
                )}
                {trade.total_risk_percent !== undefined && (
                    <DetailField label="RISK %" value={`${trade.total_risk_percent.toFixed(2)}%`} />
                )}
            </div>

            {/* Anomalies */}
            {anomalies.length > 0 && (
                <div>
                    <SectionHeader title="ANOMALIES" />
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {anomalies.map((a, i) => (
                            <div
                                key={i}
                                style={{
                                    fontSize: 10,
                                    padding: "4px 8px",
                                    borderRadius: 4,
                                    background: a.severity === "CRITICAL" ? "var(--red-glow)" : "var(--yellow-glow, rgba(255,200,0,0.06))",
                                    color: a.severity === "CRITICAL" ? "var(--red)" : "var(--yellow, #ffc800)",
                                    fontFamily: "var(--font-mono)",
                                }}
                            >
                                [{a.type}] {a.message}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Execution Timeline */}
            <div data-testid="execution-timeline">
                <SectionHeader title="EXECUTION TIMELINE" />
                <ExecutionTimelineDrawer timeline={timeline} />
            </div>
        </div>
    );
}

// ── Small helpers ────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
    return (
        <div
            style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.12em",
                color: "var(--text-muted)",
                fontFamily: "var(--font-mono)",
                marginBottom: 8,
                borderBottom: "1px solid var(--border-subtle)",
                paddingBottom: 4,
            }}
        >
            {title}
        </div>
    );
}

function DetailField({
    label,
    value,
    color,
}: {
    label: string;
    value: React.ReactNode;
    color?: string;
}) {
    return (
        <div>
            <div
                style={{
                    fontSize: 8,
                    fontWeight: 700,
                    letterSpacing: "0.12em",
                    color: "var(--text-muted)",
                    fontFamily: "var(--font-mono)",
                }}
            >
                {label}
            </div>
            <div
                className="num"
                style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: color ?? "var(--text-primary)",
                    marginTop: 1,
                }}
            >
                {value ?? "—"}
            </div>
        </div>
    );
}
