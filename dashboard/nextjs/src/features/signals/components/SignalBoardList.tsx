"use client";

import type { CSSProperties } from "react";
import type { SignalViewModel } from "../model/signal.types";

interface Props {
    signals: SignalViewModel[];
    selectedId: string | null;
    onSelect: (id: string) => void;
}

export function SignalBoardList({ signals, selectedId, onSelect }: Props) {
    return (
        <div style={{ display: "grid", gap: 10 }}>
            {signals.map((signal) => (
                <button
                    key={signal.id}
                    onClick={() => onSelect(signal.id)}
                    style={{
                        textAlign: "left",
                        padding: 12,
                        borderRadius: 10,
                        border: "1px solid rgba(255,255,255,0.1)",
                        background:
                            selectedId === signal.id ? "rgba(255,255,255,0.08)" : "transparent",
                        color: "inherit",
                        cursor: "pointer",
                    }}
                >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <strong>{signal.symbol}</strong>
                        <span>{signal.verdict}</span>
                    </div>

                    <div style={{ fontSize: 12, opacity: 0.8, marginTop: 6 }}>
                        Confidence: {(signal.confidence * 100).toFixed(0)}%
                    </div>

                    {signal.pressurePriorityContext && (
                        <div
                            style={{
                                display: "flex",
                                gap: 6,
                                flexWrap: "wrap",
                                alignItems: "center",
                                marginTop: 8,
                                fontSize: 11,
                            }}
                        >
                            <span style={pressureTierBadgeStyle(signal.pressurePriorityContext.effectivePressureTier)}>
                                {formatPressureTierLabel(signal.pressurePriorityContext.effectivePressureTier)}
                            </span>
                            {signal.pressurePriorityContext.tierScore != null && (
                                <span style={{ opacity: 0.78 }}>
                                    Score {signal.pressurePriorityContext.tierScore.toFixed(1)}
                                </span>
                            )}
                            {signal.pressurePriorityContext.lowEventHighImpactCandidate && (
                                <span style={{ color: "var(--yellow)" }}>Key level</span>
                            )}
                        </div>
                    )}

                    <div style={{ fontSize: 12, opacity: 0.8, marginTop: 4 }}>
                        RR: {signal.riskRewardRatio != null ? `1:${signal.riskRewardRatio.toFixed(2)}` : "—"} •
                        Entry: {signal.entryPrice ?? "—"} • SL: {signal.stopLoss ?? "—"}
                    </div>

                    {signal.optimisticTakeStatus && signal.optimisticTakeStatus !== "IDLE" && (
                        <div style={{ fontSize: 11, marginTop: 6, color: "var(--accent)" }}>
                            {signal.optimisticTakeStatus === "SUBMITTING" ? "TAKE SUBMITTING..." : "TAKE SUBMITTED"}
                        </div>
                    )}
                </button>
            ))}
        </div>
    );
}

function formatPressureTierLabel(tier: string): string {
    if (tier === "TIER_1_PRIMARY_ANALYSIS") return "Tier 1";
    if (tier === "TIER_2_CONFIRMATION_SUPPORT") return "Tier 2";
    if (tier === "TIER_3_KEY_LEVEL_RADAR_EXCEPTION") return "Key-level radar";
    return tier.replaceAll("_", " ");
}

function pressureTierBadgeStyle(tier: string): CSSProperties {
    const color = tier === "TIER_1_PRIMARY_ANALYSIS"
        ? "var(--green)"
        : tier === "TIER_2_CONFIRMATION_SUPPORT"
            ? "var(--blue)"
            : "var(--yellow)";

    return {
        color,
        border: `1px solid color-mix(in srgb, ${color} 38%, transparent)`,
        background: `color-mix(in srgb, ${color} 10%, transparent)`,
        borderRadius: 6,
        padding: "2px 6px",
        fontWeight: 700,
        lineHeight: 1.4,
    };
}
