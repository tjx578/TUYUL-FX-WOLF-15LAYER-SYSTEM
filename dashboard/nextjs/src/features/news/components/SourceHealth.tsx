"use client";

import { useCalendarSourceHealth } from "../api/calendar.api";

export function SourceHealth() {
    const { data } = useCalendarSourceHealth();
    if (!data) return null;
    const sources = Object.entries(data.sources ?? {});
    return (
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {sources.map(([name, rec]) => (
                <div key={name} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <span
                        style={{
                            width: 5,
                            height: 5,
                            borderRadius: "50%",
                            background: rec.healthy ? "var(--green)" : "var(--red)",
                            display: "inline-block",
                        }}
                    />
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: rec.healthy ? "var(--text-muted)" : "var(--red)" }}>
                        {name.toUpperCase()}
                    </span>
                </div>
            ))}
        </div>
    );
}
