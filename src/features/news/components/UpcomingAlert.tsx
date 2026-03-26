"use client";

import type { CalendarBlockerResponse } from "@/types";

export function UpcomingAlert({ blocker }: { blocker: CalendarBlockerResponse }) {
    if (!blocker || blocker.upcoming_count <= 0 || blocker.is_locked) return null;

    return (
        <div
            className="panel"
            style={{
                padding: "10px 14px",
                borderColor: "var(--border-warn)",
                background: "var(--yellow-glow)",
                display: "flex",
                alignItems: "center",
                gap: 10,
                fontSize: 11,
            }}
        >
            <span
                style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: "var(--yellow)",
                    display: "inline-block",
                    animation: "pulse-dot 1.5s ease-in-out infinite",
                    flexShrink: 0,
                }}
            />
            <span style={{ color: "var(--yellow)", fontWeight: 700 }}>
                {blocker.upcoming_count} upcoming high-impact event{blocker.upcoming_count > 1 ? "s" : ""}
            </span>
            <span style={{ color: "var(--text-muted)" }}>— monitor news lock window.</span>
        </div>
    );
}
