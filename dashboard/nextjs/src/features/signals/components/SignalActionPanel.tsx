"use client";

import type { SignalViewModel } from "../model/signal.types";

interface Props {
    signal: SignalViewModel | null;
    onTake: () => void;
    disabled?: boolean;
}

export function SignalActionPanel({
    signal,
    onTake,
    disabled = false,
}: Props) {
    if (!signal) {
        return (
            <div
                style={{
                    padding: 12,
                    borderRadius: 10,
                    border: "1px dashed rgba(255,255,255,0.16)",
                    opacity: 0.8,
                }}
            >
                Select a signal to review and take action.
            </div>
        );
    }

    const canTake =
        !!signal.signalId &&
        signal.verdict.startsWith("EXECUTE") &&
        !disabled;

    return (
        <div
            style={{
                padding: 16,
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.12)",
                display: "grid",
                gap: 10,
            }}
        >
            <div style={{ fontWeight: 700, fontSize: 14 }}>Operator Actions</div>

            <div style={{ fontSize: 12, opacity: 0.85 }}>
                This action does not create market direction. It binds an existing
                backend signal to an eligible account + EA instance.
            </div>

            {!signal.signalId && (
                <div
                    style={{
                        fontSize: 12,
                        color: "var(--red)",
                        padding: 10,
                        borderRadius: 8,
                        background: "rgba(255,61,87,0.08)",
                        border: "1px solid rgba(255,61,87,0.18)",
                    }}
                >
                    Missing authoritative <code>signal_id</code>. Take action is blocked.
                </div>
            )}

            {!signal.verdict.startsWith("EXECUTE") && (
                <div
                    style={{
                        fontSize: 12,
                        color: "var(--yellow)",
                        padding: 10,
                        borderRadius: 8,
                        background: "rgba(255,215,64,0.08)",
                        border: "1px solid rgba(255,215,64,0.18)",
                    }}
                >
                    This verdict is <strong>{signal.verdict}</strong>. Only EXECUTE-class
                    verdicts should be routed to account selection.
                </div>
            )}

            <button
                type="button"
                onClick={onTake}
                disabled={!canTake}
                style={{
                    padding: "10px 14px",
                    borderRadius: 10,
                    border: "1px solid rgba(0,230,118,0.25)",
                    background: canTake ? "rgba(0,230,118,0.08)" : "transparent",
                    color: canTake ? "var(--green)" : "var(--text-muted)",
                    cursor: canTake ? "pointer" : "not-allowed",
                    fontWeight: 700,
                    opacity: canTake ? 1 : 0.6,
                }}
            >
                Take Signal
            </button>
        </div>
    );
}
