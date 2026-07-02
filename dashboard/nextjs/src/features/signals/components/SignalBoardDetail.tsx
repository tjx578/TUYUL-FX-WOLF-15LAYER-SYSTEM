"use client";

import type { CSSProperties } from "react";
import type { SignalPressurePriorityContextViewModel, SignalViewModel } from "../model/signal.types";
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

            {signal.throttledFrom && (
                <div style={{ fontSize: 14 }}>
                    Throttle: {signal.throttledFrom} -&gt; {signal.verdict}
                </div>
            )}

            {signal.pressurePriorityContext && (
                <PressurePriorityContextPanel context={signal.pressurePriorityContext} />
            )}

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

function PressurePriorityContextPanel({
    context,
}: {
    context: SignalPressurePriorityContextViewModel;
}) {
    const memory = context.fragmentedPressureMemory;

    return (
        <div
            style={{
                display: "grid",
                gap: 8,
                padding: 12,
                borderRadius: 8,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.035)",
                fontSize: 13,
            }}
        >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                <strong>Pressure Priority</strong>
                <span style={pressureTierBadgeStyle(context.effectivePressureTier)}>
                    {formatPressureTierLabel(context.effectivePressureTier)}
                </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
                <Metric label="Score" value={context.tierScore?.toFixed(1) ?? "—"} />
                <Metric label="Action" value={formatPressureAction(context.tierAction)} />
                <Metric label="Scope" value={context.tierScope ?? "—"} />
                <Metric label="Execution impact" value={context.tierExecutionImpact ? "Yes" : "No"} />
            </div>

            {context.lowEventHighImpactCandidate && (
                <div style={{ color: "var(--yellow)", fontWeight: 700 }}>
                    Low-event key-level candidate
                </div>
            )}

            {memory && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", opacity: 0.86 }}>
                    {memory.pressureMemoryScore != null && (
                        <span>Memory {memory.pressureMemoryScore.toFixed(1)}</span>
                    )}
                    {memory.sameSymbolReentryCount != null && (
                        <span>Re-entry {memory.sameSymbolReentryCount}</span>
                    )}
                    {memory.cleanBlockCount != null && (
                        <span>Clean blocks {memory.cleanBlockCount}</span>
                    )}
                </div>
            )}
        </div>
    );
}

function Metric({ label, value }: { label: string; value: string }) {
    return (
        <div style={{ minWidth: 0 }}>
            <div style={{ opacity: 0.65, fontSize: 11 }}>{label}</div>
            <div style={{ overflowWrap: "anywhere" }}>{value}</div>
        </div>
    );
}

function formatPressureTierLabel(tier: string): string {
    if (tier === "TIER_1_PRIMARY_ANALYSIS") return "Tier 1";
    if (tier === "TIER_2_CONFIRMATION_SUPPORT") return "Tier 2";
    if (tier === "TIER_3_KEY_LEVEL_RADAR_EXCEPTION") return "Key-level radar";
    return tier.replaceAll("_", " ");
}

function formatPressureAction(action?: string): string {
    if (action === "PRIORITIZE_ANALYSIS") return "Prioritize";
    if (action === "CONFIRMATION_SUPPORT") return "Confirm";
    if (action === "RADAR_EXCEPTION_ONLY") return "Radar only";
    return action?.replaceAll("_", " ") ?? "—";
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
