"use client";

import type { FreshnessClassLabel } from "@/types";

interface Props {
    freshnessClass?: FreshnessClassLabel;
    wsStatus: string;
    isStale: boolean;
}

export function SignalFreshnessStrip({ freshnessClass, wsStatus, isStale }: Props) {
    const message =
        freshnessClass === "LIVE"
            ? "LIVE — data fresh and signal board is legitimate for operator review"
            : freshnessClass
                ? `${freshnessClass} — review transport / producer / freshness before trusting signal actions`
                : "UNKNOWN — freshness class unavailable";

    return (
        <div
            style={{
                padding: "10px 12px",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 10,
            }}
        >
            <div style={{ fontWeight: 700 }}>
                Freshness: {freshnessClass ?? "UNKNOWN"}
            </div>
            <div style={{ fontSize: 12, opacity: 0.8, marginTop: 4 }}>{message}</div>
            <div style={{ fontSize: 12, opacity: 0.8, marginTop: 4 }}>
                WS: {wsStatus} {isStale ? "• STALE" : ""}
            </div>
        </div>
    );
}
