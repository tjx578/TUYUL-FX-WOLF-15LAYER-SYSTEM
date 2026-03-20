"use client";

import type { VerdictEmptyState } from "@/lib/verdictEmptyState";

interface VerdictEmptyStatePanelProps {
    state: VerdictEmptyState | null;
    fallbackTitle?: string;
    fallbackDetail?: string;
}

export default function VerdictEmptyStatePanel({
    state,
    fallbackTitle = "No verdict available",
    fallbackDetail = "Connect backend to see live signals.",
}: VerdictEmptyStatePanelProps) {
    return (
        <div
            className="panel"
            style={{
                fontSize: 12,
                color: "var(--text-muted)",
                padding: "32px 20px",
                textAlign: "center",
            }}
        >
            {state?.badgeLabel && (
                <div style={{ marginBottom: 8 }}>
                    <span className={state.badgeClass} style={{ fontSize: 9, letterSpacing: "0.12em" }}>
                        {state.badgeLabel}
                    </span>
                </div>
            )}
            <div
                style={{
                    marginBottom: 6,
                    fontSize: 13,
                    color: "var(--text-secondary)",
                }}
            >
                {state?.title ?? fallbackTitle}
            </div>
            <div style={{ fontSize: 11 }}>
                {state?.detail ?? fallbackDetail}
            </div>
        </div>
    );
}
