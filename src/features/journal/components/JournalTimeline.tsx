"use client";

import { formatTime } from "@/lib/timezone";
import type { DailyJournal, JournalEntry } from "@/types";

const ACTION_COLOR: Record<string, string> = {
    TAKE: "var(--green)",
    OPEN: "var(--blue)",
    CLOSE: "var(--accent)",
    SKIP: "var(--text-muted)",
};

const OUTCOME_COLOR: Record<string, string> = {
    WIN: "var(--green)",
    LOSS: "var(--red)",
    BREAKEVEN: "var(--yellow)",
};

interface JournalTimelineProps {
    journal: DailyJournal;
}

export function JournalTimeline({ journal }: JournalTimelineProps) {
    if (!journal.entries || journal.entries.length === 0) {
        return (
            <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 8 }}>
                No journal entries.
            </div>
        );
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {journal.entries.map((entry) => (
                <TimelineEntry key={entry.entry_id} entry={entry} />
            ))}
        </div>
    );
}

function TimelineEntry({ entry }: { entry: JournalEntry }) {
    const actionColor = ACTION_COLOR[entry.action] ?? "var(--text-muted)";
    const outcomeColor = entry.outcome
        ? OUTCOME_COLOR[entry.outcome] ?? "var(--text-muted)"
        : undefined;

    return (
        <div
            style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "6px 10px",
                borderLeft: `2px solid ${actionColor}`,
                borderRadius: 2,
                background: "var(--bg-card)",
            }}
        >
            {/* Time */}
            <span
                className="num"
                style={{
                    fontSize: 10,
                    color: "var(--text-muted)",
                    minWidth: 55,
                    flexShrink: 0,
                }}
            >
                {formatTime(entry.timestamp).slice(0, 5)}
            </span>

            {/* Action badge */}
            <span
                style={{
                    fontSize: 9,
                    fontWeight: 700,
                    letterSpacing: "0.06em",
                    color: actionColor,
                    minWidth: 36,
                }}
            >
                {entry.action}
            </span>

            {/* Journal type */}
            <span
                className="badge"
                style={{
                    fontSize: 8,
                    background: "var(--bg-panel)",
                    color: "var(--text-muted)",
                    borderColor: "var(--bg-border)",
                }}
            >
                {entry.journal_type}
            </span>

            {/* Pair + direction */}
            <span
                style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: "var(--text-primary)",
                }}
            >
                {entry.pair}
            </span>
            {entry.direction && (
                <span
                    style={{
                        fontSize: 10,
                        fontWeight: 700,
                        color:
                            entry.direction === "BUY" ? "var(--green)" : "var(--red)",
                    }}
                >
                    {entry.direction}
                </span>
            )}

            {/* Spacer */}
            <span style={{ flex: 1 }} />

            {/* Outcome + PnL */}
            {entry.outcome && (
                <span
                    style={{
                        fontSize: 10,
                        fontWeight: 700,
                        color: outcomeColor,
                        letterSpacing: "0.04em",
                    }}
                >
                    {entry.outcome}
                </span>
            )}
            {entry.pnl !== undefined && (
                <span
                    className="num"
                    style={{
                        fontSize: 12,
                        fontWeight: 700,
                        color: entry.pnl >= 0 ? "var(--green)" : "var(--red)",
                    }}
                >
                    {entry.pnl >= 0 ? "+" : ""}
                    {entry.pnl.toFixed(2)}
                </span>
            )}
            {entry.rr_achieved !== undefined && (
                <span
                    className="num"
                    style={{ fontSize: 10, color: "var(--accent)" }}
                >
                    {entry.rr_achieved.toFixed(1)}R
                </span>
            )}
        </div>
    );
}
