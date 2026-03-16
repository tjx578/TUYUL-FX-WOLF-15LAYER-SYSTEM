"use client";

// ============================================================
// TUYUL FX Wolf-15 — Account Readiness Badge
// Visual readiness indicator (0–100%) with color coding.
// ============================================================

interface AccountReadinessBadgeProps {
    score: number; // 0.0 – 1.0
    size?: "sm" | "md";
}

function readinessColor(score: number): string {
    if (score >= 0.8) return "var(--green)";
    if (score >= 0.5) return "var(--yellow)";
    if (score >= 0.2) return "var(--orange, var(--yellow))";
    return "var(--red)";
}

function readinessLabel(score: number): string {
    if (score >= 0.8) return "READY";
    if (score >= 0.5) return "PARTIAL";
    if (score >= 0.2) return "LIMITED";
    return "BLOCKED";
}

export default function AccountReadinessBadge({ score, size = "sm" }: AccountReadinessBadgeProps) {
    const normalizedScore = score > 1 ? score / 100 : score;
    const pct = Math.round(normalizedScore * 100);
    const color = readinessColor(normalizedScore);
    const label = readinessLabel(normalizedScore);
    const fontSize = size === "md" ? 11 : 9;
    const padding = size === "md" ? "4px 8px" : "2px 6px";

    return (
        <span
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding,
                borderRadius: 9999,
                border: `1px solid ${color}30`,
                background: `${color}10`,
                fontSize,
                fontWeight: 700,
                letterSpacing: "0.06em",
                color,
                fontFamily: "var(--font-mono)",
            }}
        >
            <span
                style={{
                    width: size === "md" ? 7 : 5,
                    height: size === "md" ? 7 : 5,
                    borderRadius: "50%",
                    background: color,
                    flexShrink: 0,
                }}
            />
            {pct}% {label}
        </span>
    );
}
