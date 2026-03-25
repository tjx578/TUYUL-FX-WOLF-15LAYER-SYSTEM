"use client";

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

                    <div style={{ fontSize: 12, opacity: 0.8, marginTop: 4 }}>
                        RR: {signal.riskRewardRatio ? `1:${signal.riskRewardRatio.toFixed(2)}` : "—"} •
                        Entry: {signal.entryPrice ?? "—"} • SL: {signal.stopLoss ?? "—"}
                    </div>
                </button>
            ))}
        </div>
    );
}
