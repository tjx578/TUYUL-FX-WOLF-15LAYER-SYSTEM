"use client";

import { useEffect, useMemo, useState } from "react";
import type { SignalViewModel } from "../model/signal.types";
import type { TakeSignalAccountOption, TakeSignalResponseVM } from "../api/signalActions.api";
import { useTakeSignalFlow } from "../hooks/useTakeSignalFlow";
import { EligibleAccountsPanel } from "./EligibleAccountsPanel";
import { RiskPreviewPanel } from "./RiskPreviewPanel";
import type { PostTakeRouteTarget } from "@/shared/contracts/lifecycleNavigation";

interface Props {
    open: boolean;
    signal: SignalViewModel | null;
    accounts: TakeSignalAccountOption[];
    operatorId: string;
    onClose: () => void;
    onSubmitted?: (
        result: TakeSignalResponseVM,
        target: PostTakeRouteTarget,
    ) => void;
}

export function TakeSignalDrawer({
    open,
    signal,
    accounts,
    operatorId,
    onClose,
    onSubmitted,
}: Props) {
    const [target, setTarget] = useState<PostTakeRouteTarget>("trades");

    const selectableAccounts = useMemo(
        () =>
            accounts.map((a) => ({
                ...a,
                selectable:
                    a.selectable !== false &&
                    !!a.eaInstanceId &&
                    a.riskState !== "CRITICAL",
                eligibilityReason:
                    a.eligibilityReason ??
                    (!a.eaInstanceId
                        ? "No EA instance linked"
                        : a.riskState === "CRITICAL"
                            ? "Account in CRITICAL risk state"
                            : null),
            })),
        [accounts],
    );

    const flow = useTakeSignalFlow({
        signal,
        accounts: selectableAccounts,
        operatorId,
        onSubmitted: (result) => onSubmitted?.(result, target),
    });

    useEffect(() => {
        if (open) flow.open();
        else flow.close();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open]);

    if (!open || !signal) return null;

    return (
        <div
            style={{
                position: "fixed",
                inset: 0,
                background: "rgba(0,0,0,0.55)",
                display: "flex",
                justifyContent: "flex-end",
                zIndex: 1000,
            }}
        >
            <div
                style={{
                    width: "min(640px, 100%)",
                    height: "100%",
                    background: "#0b0f17",
                    borderLeft: "1px solid rgba(255,255,255,0.12)",
                    padding: 20,
                    overflowY: "auto",
                    display: "grid",
                    gap: 16,
                }}
            >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <div>
                        <h2 style={{ margin: 0 }}>Take Signal</h2>
                        <div style={{ marginTop: 4, opacity: 0.8, fontSize: 13 }}>
                            {signal.symbol} • {signal.verdict} • {(signal.confidence * 100).toFixed(0)}%
                        </div>
                    </div>

                    <button
                        type="button"
                        onClick={() => {
                            flow.close();
                            onClose();
                        }}
                        style={{
                            borderRadius: 8,
                            border: "1px solid rgba(255,255,255,0.12)",
                            background: "transparent",
                            color: "inherit",
                            padding: "8px 10px",
                            cursor: "pointer",
                        }}
                    >
                        Close
                    </button>
                </div>

                {!signal.signalId && (
                    <div
                        style={{
                            padding: 12,
                            borderRadius: 10,
                            border: "1px solid rgba(255,61,87,0.22)",
                            color: "var(--red)",
                        }}
                    >
                        Backend authoritative <code>signal_id</code> is missing from this signal.
                        Take action is blocked for safety.
                    </div>
                )}

                <div
                    style={{
                        padding: 12,
                        borderRadius: 10,
                        border: "1px solid rgba(255,255,255,0.12)",
                        display: "grid",
                        gap: 8,
                    }}
                >
                    <div><strong>Entry</strong>: {signal.entryPrice ?? "—"}</div>
                    <div><strong>SL</strong>: {signal.stopLoss ?? "—"}</div>
                    <div><strong>TP1</strong>: {signal.takeProfit1 ?? "—"}</div>
                    <div><strong>RR</strong>: {signal.riskRewardRatio ? `1:${signal.riskRewardRatio.toFixed(2)}` : "—"}</div>
                    <div><strong>Signal ID</strong>: {signal.signalId ?? "—"}</div>
                    <div><strong>Expires</strong>: {signal.expiresAt ?? "—"}</div>
                </div>

                <div style={{ display: "grid", gap: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>After submit</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        {(["signals", "trades", "accounts"] as const).map((value) => (
                            <button
                                key={value}
                                type="button"
                                onClick={() => setTarget(value)}
                                style={{
                                    padding: "8px 12px",
                                    borderRadius: 10,
                                    border: target === value
                                        ? "1px solid var(--accent)"
                                        : "1px solid rgba(255,255,255,0.12)",
                                    background: target === value ? "rgba(0,229,255,0.08)" : "transparent",
                                    color: "inherit",
                                    cursor: "pointer",
                                }}
                            >
                                Go to /{value}
                            </button>
                        ))}
                    </div>
                </div>

                <div style={{ display: "grid", gap: 8 }}>
                    <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700 }}>Operator Reason</span>
                        <textarea
                            value={flow.reason}
                            onChange={(e) => flow.setReason(e.target.value)}
                            rows={3}
                            style={{
                                width: "100%",
                                borderRadius: 10,
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "transparent",
                                color: "inherit",
                                padding: 10,
                            }}
                        />
                    </label>

                    <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 700 }}>Risk %</span>
                        <input
                            type="number"
                            min={0.01}
                            max={5}
                            step={0.01}
                            value={flow.riskPercent}
                            onChange={(e) => flow.setRiskPercent(Number(e.target.value))}
                            style={{
                                width: 140,
                                borderRadius: 10,
                                border: "1px solid rgba(255,255,255,0.12)",
                                background: "transparent",
                                color: "inherit",
                                padding: 10,
                            }}
                        />
                    </label>
                </div>

                <div>
                    <div style={{ fontWeight: 700, marginBottom: 8 }}>Eligible Accounts</div>
                    <EligibleAccountsPanel
                        accounts={selectableAccounts}
                        selectedAccountId={flow.selectedAccountId}
                        onSelect={flow.selectAccount}
                        disabled={flow.isSubmitting}
                    />
                </div>

                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <button
                        type="button"
                        onClick={flow.runPreview}
                        disabled={!signal.signalId || !flow.selectedAccountId || flow.isPreviewing || flow.isSubmitting}
                        style={{
                            padding: "10px 14px",
                            borderRadius: 10,
                            border: "1px solid rgba(255,255,255,0.12)",
                            background: "transparent",
                            color: "inherit",
                            cursor: "pointer",
                            opacity:
                                !signal.signalId || !flow.selectedAccountId || flow.isPreviewing || flow.isSubmitting
                                    ? 0.6
                                    : 1,
                        }}
                    >
                        {flow.isPreviewing ? "Previewing..." : "Preview Risk"}
                    </button>

                    <button
                        type="button"
                        onClick={async () => {
                            const result = await flow.submit();
                            if (result) onClose();
                        }}
                        disabled={!flow.canSubmit}
                        style={{
                            padding: "10px 14px",
                            borderRadius: 10,
                            border: "1px solid rgba(0,230,118,0.25)",
                            background: "rgba(0,230,118,0.08)",
                            color: "var(--green)",
                            cursor: "pointer",
                            opacity: flow.canSubmit ? 1 : 0.55,
                        }}
                    >
                        {flow.isSubmitting ? "Submitting..." : "Take Signal"}
                    </button>
                </div>

                <RiskPreviewPanel
                    isPreviewing={flow.isPreviewing}
                    preview={flow.preview}
                    error={flow.error}
                />
            </div>
        </div>
    );
}
