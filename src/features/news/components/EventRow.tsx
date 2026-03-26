"use client";

import type { CalendarEvent } from "@/types";
import { ImpactBadge } from "./ImpactBadge";

export function EventRow({ event }: { event: CalendarEvent }) {
    const isHigh = event.impact === "HIGH";
    const isImminent = event.is_imminent;

    return (
        <tr
            className={isImminent ? "animate-fade-in" : ""}
            style={{
                background: isImminent ? "rgba(255,215,64,0.04)" : undefined,
                borderLeft: isHigh ? "2px solid var(--red)" : "2px solid transparent",
            }}
        >
            <td>
                <span className="num" style={{ fontSize: 11, color: isImminent ? "var(--yellow)" : "var(--text-muted)" }}>
                    {event.time ?? "—"}
                </span>
                {isImminent && (
                    <span
                        style={{
                            marginLeft: 5,
                            fontSize: 9,
                            fontFamily: "var(--font-mono)",
                            color: "var(--yellow)",
                            fontWeight: 700,
                        }}
                    >
                        SOON
                    </span>
                )}
            </td>
            <td>
                <span
                    className="badge badge-muted num"
                    style={{ fontSize: 10, fontWeight: 800 }}
                >
                    {event.currency}
                </span>
            </td>
            <td><ImpactBadge impact={event.impact} /></td>
            <td style={{ color: "var(--text-primary)", fontSize: 12 }}>
                {event.event ?? event.title ?? "—"}
            </td>
            <td>
                <div style={{ display: "flex", gap: 10, fontFamily: "var(--font-mono)", fontSize: 11 }}>
                    <span style={{ color: "var(--text-muted)" }}>
                        P: {event.previous ?? "—"}
                    </span>
                    <span style={{ color: "var(--text-secondary)" }}>
                        F: {event.forecast ?? "—"}
                    </span>
                    {event.actual != null && (
                        <span style={{ color: "var(--accent)", fontWeight: 700 }}>
                            A: {event.actual}
                        </span>
                    )}
                </div>
            </td>
        </tr>
    );
}
