"use client";

// ============================================================
// TUYUL FX Wolf-15 — Account Eligibility Panel
// Shows eligibility flags + lock reasons for an account.
// ============================================================

import type { EligibilityFlags } from "@/types";

interface AccountEligibilityPanelProps {
    flags: EligibilityFlags;
    lockReasons: string[];
}

const FLAG_LABELS: Record<keyof EligibilityFlags, string> = {
    compliance_ok: "Compliance",
    circuit_breaker_ok: "Circuit Breaker",
    not_locked: "Unlocked",
    no_news_lock: "No News Lock",
    daily_dd_ok: "Daily DD Safe",
    total_dd_ok: "Total DD Safe",
    slots_available: "Slots Open",
    ea_linked: "EA Linked",
};

export default function AccountEligibilityPanel({ flags, lockReasons }: AccountEligibilityPanelProps) {
    const entries = Object.entries(flags) as [keyof EligibilityFlags, boolean][];

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {/* Flag grid */}
            <div
                style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(2, 1fr)",
                    gap: 6,
                }}
            >
                {entries.map(([key, ok]) => (
                    <div
                        key={key}
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                            fontSize: 10,
                            color: ok ? "var(--green)" : "var(--red)",
                        }}
                    >
                        <span style={{ fontSize: 12 }}>{ok ? "✓" : "✗"}</span>
                        <span style={{ letterSpacing: "0.04em" }}>
                            {FLAG_LABELS[key] ?? key}
                        </span>
                    </div>
                ))}
            </div>

            {/* Lock reasons */}
            {lockReasons.length > 0 && (
                <div
                    style={{
                        padding: "8px 10px",
                        borderRadius: 6,
                        background: "var(--red-glow, rgba(239,68,68,0.05))",
                        border: "1px solid var(--border-danger, rgba(239,68,68,0.15))",
                    }}
                >
                    <div
                        style={{
                            fontSize: 9,
                            fontWeight: 700,
                            letterSpacing: "0.1em",
                            color: "var(--red)",
                            marginBottom: 4,
                        }}
                    >
                        LOCK REASONS
                    </div>
                    {lockReasons.map((reason) => (
                        <div
                            key={reason}
                            style={{ fontSize: 10, color: "var(--text-secondary)", padding: "1px 0" }}
                        >
                            • {reason}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
