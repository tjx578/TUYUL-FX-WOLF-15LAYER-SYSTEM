"use client";

import type { RiskPreviewResult } from "../api/signalActions.api";

interface Props {
    isPreviewing: boolean;
    preview: RiskPreviewResult | null;
    error?: string | null;
}

export function RiskPreviewPanel({ isPreviewing, preview, error }: Props) {
    if (isPreviewing) {
        return (
            <div
                style={{
                    padding: 12,
                    borderRadius: 10,
                    border: "1px solid rgba(255,255,255,0.12)",
                }}
            >
                Calculating risk preview...
            </div>
        );
    }

    if (error && !preview) {
        return (
            <div
                style={{
                    padding: 12,
                    borderRadius: 10,
                    border: "1px solid rgba(255,61,87,0.22)",
                    color: "var(--red)",
                }}
            >
                {error}
            </div>
        );
    }

    if (!preview) {
        return (
            <div
                style={{
                    padding: 12,
                    borderRadius: 10,
                    border: "1px dashed rgba(255,255,255,0.16)",
                    opacity: 0.8,
                }}
            >
                Select an account and run preview to calculate lot size and DD impact.
            </div>
        );
    }

    return (
        <div
            style={{
                padding: 12,
                borderRadius: 10,
                border: `1px solid ${preview.allowed ? "rgba(0,230,118,0.22)" : "rgba(255,61,87,0.22)"
                    }`,
                display: "grid",
                gap: 8,
            }}
        >
            <div style={{ fontWeight: 700, color: preview.allowed ? "var(--green)" : "var(--red)" }}>
                {preview.allowed ? "RISK PREVIEW APPROVED" : "RISK PREVIEW REJECTED"}
            </div>

            <div style={{ fontSize: 13 }}>
                Lot Size: <strong>{preview.lotSize.toFixed(2)}</strong>
            </div>

            <div style={{ fontSize: 13 }}>
                Risk %: <strong>{preview.riskPercent.toFixed(2)}%</strong>
            </div>

            <div style={{ fontSize: 13 }}>
                Daily DD After: <strong>{preview.dailyDdAfter.toFixed(2)}%</strong>
            </div>

            {preview.reason && (
                <div style={{ fontSize: 12, opacity: 0.85 }}>{preview.reason}</div>
            )}
        </div>
    );
}
