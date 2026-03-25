"use client";

import type { TradeLifecycleBridgeViewModel } from "../model/trade.types";

interface Props {
    lifecycle: TradeLifecycleBridgeViewModel | null;
    fallback: {
        takeId: string | null;
        accountId: string | null;
        signalId: string | null;
    };
}

export function TradeBridgeBanner({ lifecycle, fallback }: Props) {
    const status = lifecycle?.status ?? "UNKNOWN";
    const takeId = lifecycle?.takeId ?? fallback.takeId;
    const accountId = lifecycle?.accountId ?? fallback.accountId;
    const signalId = lifecycle?.signalId ?? fallback.signalId;

    return (
        <div
            style={{
                padding: 12,
                borderRadius: 10,
                border: "1px solid rgba(0,229,255,0.18)",
                background: "rgba(0,229,255,0.06)",
                fontSize: 13,
                display: "grid",
                gap: 6,
            }}
        >
            <strong>Take-Signal Lifecycle Monitor</strong>
            <div>Status: {status}</div>
            {takeId && <div>takeId: {takeId}</div>}
            {accountId && <div>accountId: {accountId}</div>}
            {signalId && <div>signalId: {signalId}</div>}
            {lifecycle?.statusReason && <div>Reason: {lifecycle.statusReason}</div>}
        </div>
    );
}
