"use client";

import type { DailyJournal } from "@/types";
import { JournalTimeline } from "./JournalTimeline";

export function JournalWeeklyDay({ day }: { day: DailyJournal }) {
    return (
        <div className="panel" style={{ padding: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
                    {day.date}
                </span>
                <div style={{ display: "flex", gap: 12, fontSize: 11, alignItems: "center" }}>
                    <span style={{ color: "var(--text-muted)" }}>
                        Trades: <span className="num" style={{ color: "var(--text-secondary)" }}>{day.metrics.total_trades}</span>
                    </span>
                    <span style={{ color: "var(--text-muted)" }}>
                        WR:{" "}
                        <span
                            className="num"
                            style={{ color: day.metrics.win_rate >= 0.6 ? "var(--green)" : "var(--yellow)", fontWeight: 700 }}
                        >
                            {Math.round(day.metrics.win_rate * 100)}%
                        </span>
                    </span>
                    <span
                        className="num"
                        style={{
                            color: day.net_pnl >= 0 ? "var(--green)" : "var(--red)",
                            fontWeight: 700,
                        }}
                    >
                        {day.net_pnl >= 0 ? "+" : ""}{day.net_pnl.toFixed(2)}
                    </span>
                </div>
            </div>
            <JournalTimeline journal={day} />
        </div>
    );
}
