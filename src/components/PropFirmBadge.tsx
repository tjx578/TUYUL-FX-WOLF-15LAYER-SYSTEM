"use client";

// ============================================================
// TUYUL FX Wolf-15 — PropFirmBadge + AlertFeed
// ============================================================

import type { AlertEvent } from "@/types";
import { formatTime } from "@/lib/timezone";

// ─── AlertFeed ────────────────────────────────────────────────

interface AlertFeedProps {
    alerts: AlertEvent[];
    maxVisible?: number;
}

const ALERT_COLORS: Record<string, string> = {
    INFO: "var(--blue)",
    WARNING: "var(--yellow)",
    CRITICAL: "var(--red)",
};

const ALERT_ICONS: Record<string, string> = {
    ORDER_PLACED: "◈",
    ORDER_FILLED: "◆",
    ORDER_CANCELLED: "◇",
    SYSTEM_VIOLATION: "⚠",
    RISK_LIMIT_REACHED: "⬡",
    PROP_FIRM_BREACH: "⛔",
    CIRCUIT_BREAKER_OPEN: "⚡",
    NEWS_LOCK: "📰",
    SESSION_CHANGE: "🕐",
};

export function AlertFeed({ alerts, maxVisible = 10 }: AlertFeedProps) {
    const visible = alerts.slice(0, maxVisible);

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div
                style={{
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.1em",
                    color: "var(--text-muted)",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                }}
            >
                ALERTS
                {alerts.length > 0 && (
                    <span className="badge badge-gold" style={{ fontSize: 9 }}>
                        {alerts.length}
                    </span>
                )}
            </div>

            {visible.length === 0 ? (
                <div
                    style={{
                        fontSize: 11,
                        color: "var(--text-muted)",
                        padding: "16px 0",
                        textAlign: "center",
                    }}
                >
                    No alerts
                </div>
            ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {visible.map((alert, i) => {
                        const color = ALERT_COLORS[alert.severity] ?? "var(--text-muted)";
                        const icon = ALERT_ICONS[alert.type] ?? "•";
                        return (
                            <div
                                key={alert.alert_id || i}
                                className="animate-fade-in"
                                style={{
                                    display: "flex",
                                    gap: 8,
                                    padding: "6px 10px",
                                    borderRadius: 4,
                                    background: `${color}08`,
                                    border: `1px solid ${color}15`,
                                    fontSize: 11,
                                }}
                            >
                                <span style={{ color, flexShrink: 0 }}>{icon}</span>
                                <div style={{ flex: 1 }}>
                                    <div style={{ color: "var(--text-secondary)" }}>
                                        {alert.message}
                                    </div>
                                    <div
                                        style={{
                                            fontSize: 9,
                                            color: "var(--text-muted)",
                                            fontFamily: "var(--font-mono)",
                                            marginTop: 2,
                                        }}
                                    >
                                        {alert.pair && `${alert.pair} · `}
                                        {formatTime(alert.timestamp)}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

// ─── PropFirmBadge ────────────────────────────────────────────

interface PropFirmBadgeProps {
    code?: string;
    active?: boolean;
}

export function PropFirmBadge({ code, active = true }: PropFirmBadgeProps) {
    if (!code) return null;

    return (
        <span
            className={`badge ${active ? "badge-gold" : "badge-muted"}`}
            style={{ fontSize: 10 }}
        >
            {code}
        </span>
    );
}
