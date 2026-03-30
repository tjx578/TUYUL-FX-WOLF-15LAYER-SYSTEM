"use client";

import React from "react";
import type { ExposureSummary } from "../model/tradeDeskSchema";

// ── ExposureSummaryPanel ─────────────────────────────────────

interface ExposureSummaryPanelProps {
    exposure: ExposureSummary | null;
}

export function ExposureSummaryPanel({ exposure }: ExposureSummaryPanelProps) {
    if (!exposure || (exposure.total_trades === 0)) {
        return (
            <div
                className="card"
                style={{ padding: "12px 14px", fontSize: 11, color: "var(--text-muted)" }}
            >
                No active exposure.
            </div>
        );
    }

    return (
        <div className="card" data-testid="exposure-panel" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12 }}>
            {/* Summary header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div
                    style={{
                        fontSize: 9,
                        fontWeight: 700,
                        letterSpacing: "0.12em",
                        color: "var(--text-muted)",
                        fontFamily: "var(--font-mono)",
                    }}
                >
                    EXPOSURE SUMMARY
                </div>
                <div
                    className="num"
                    style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)" }}
                >
                    {exposure.total_lots.toFixed(2)} lots · {exposure.total_trades} trades
                </div>
            </div>

            {/* By Pair */}
            {exposure.by_pair.length > 0 && (
                <div>
                    <div
                        style={{
                            fontSize: 8,
                            fontWeight: 700,
                            letterSpacing: "0.1em",
                            color: "var(--text-muted)",
                            fontFamily: "var(--font-mono)",
                            marginBottom: 6,
                        }}
                    >
                        BY PAIR
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {exposure.by_pair.map((p) => (
                            <div
                                key={p.pair}
                                className="num"
                                style={{
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    padding: "4px 8px",
                                    borderRadius: 4,
                                    background: "var(--bg-elevated)",
                                    fontSize: 11,
                                }}
                            >
                                <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{p.pair}</span>
                                <div style={{ display: "flex", gap: 10, color: "var(--text-secondary)" }}>
                                    {p.buy_lots > 0 && (
                                        <span style={{ color: "var(--green)" }}>↑ {p.buy_lots.toFixed(2)}</span>
                                    )}
                                    {p.sell_lots > 0 && (
                                        <span style={{ color: "var(--red)" }}>↓ {p.sell_lots.toFixed(2)}</span>
                                    )}
                                    <span>{p.count} trades</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* By Account */}
            {exposure.by_account.length > 0 && (
                <div>
                    <div
                        style={{
                            fontSize: 8,
                            fontWeight: 700,
                            letterSpacing: "0.1em",
                            color: "var(--text-muted)",
                            fontFamily: "var(--font-mono)",
                            marginBottom: 6,
                        }}
                    >
                        BY ACCOUNT
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {exposure.by_account.map((a) => (
                            <div
                                key={a.account_id}
                                className="num"
                                style={{
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    padding: "4px 8px",
                                    borderRadius: 4,
                                    background: "var(--bg-elevated)",
                                    fontSize: 11,
                                }}
                            >
                                <span style={{ color: "var(--text-secondary)" }}>{a.account_id.slice(0, 12)}</span>
                                <div style={{ display: "flex", gap: 10, color: "var(--text-secondary)" }}>
                                    <span>{a.total_lots.toFixed(2)} lots</span>
                                    <span>{a.count} trades</span>
                                    <span style={{ color: "var(--text-muted)" }}>{(a.pairs ?? []).join(", ")}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
