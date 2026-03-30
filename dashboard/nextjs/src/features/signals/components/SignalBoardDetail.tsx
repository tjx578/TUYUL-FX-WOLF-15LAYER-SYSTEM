"use client";

import type { SignalViewModel } from "../model/signal.types";
import { SignalActionPanel } from "./SignalActionPanel";

interface Props {
    signal: SignalViewModel | null;
    onTake: () => void;
    isBusy?: boolean;
}

export function SignalBoardDetail({
    signal,
    onTake,
    isBusy = false,
}: Props) {
    if (!signal) {
        return (
            <div
                style={{
                    padding: 16,
                    borderRadius: 10,
                    border: "1px solid rgba(255,255,255,0.1)",
                }}
            >
                Select a signal to inspect gates, scores, expiry, and hold reason.
            </div>
        );
    }

    return (
        <div
            style={{
                padding: 16,
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.1)",
                display: "grid",
                gap: 12,
            }}
        >
            <div>
                <h2 style={{ margin: 0 }}>{signal.symbol}</h2>
                <div style={{ marginTop: 4, opacity: 0.8 }}>
                    {signal.verdict} • {(signal.confidence * 100).toFixed(0)}%
                </div>
            </div>

            <div style={{ fontSize: 14 }}>
                Direction: {signal.direction ?? "—"}
            </div>
            <div style={{ fontSize: 14 }}>
                Entry: {signal.entryPrice ?? "—"} • SL: {signal.stopLoss ?? "—"} • TP1:{" "}
                {signal.takeProfit1 ?? "—"}
            </div>
            <div style={{ fontSize: 14 }}>
                RR: {signal.riskRewardRatio ? `1:${signal.riskRewardRatio.toFixed(2)}` : "—"}
            </div>
            <div style={{ fontSize: 14 }}>
                Expires: {signal.expiresAt ?? "—"}
            </div>
            <div style={{ fontSize: 14 }}>
                Signal ID: {signal.signalId ?? "—"}
            </div>

            {signal.scores && (
                <div style={{ fontSize: 14 }}>
                    Wolf: {signal.scores.wolfScore ?? "—"} • TII: {signal.scores.tiiScore ?? "—"} •
                    FRPC: {signal.scores.frpcScore ?? "—"}
                </div>
            )}

            <div>
                <strong>Gates</strong>
                <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
                    {(signal.gates ?? []).map((g) => (
                        <div key={g.gateId} style={{ fontSize: 13 }}>
                            {g.passed ? "✓" : "✗"} {g.name}
                            {g.message ? ` — ${g.message}` : ""}
                        </div>
                    ))}
                </div>
            </div>

            {signal.holdReason && (
                <div style={{ fontSize: 13 }}>
                    <strong>Hold Reason:</strong> {signal.holdReason}
                </div>
            )}

            <SignalActionPanel
                signal={signal}
                onTake={onTake}
                disabled={isBusy}
            />
        </div>
    );
}
