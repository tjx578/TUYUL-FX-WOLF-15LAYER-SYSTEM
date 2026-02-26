"use client";

// ============================================================
// TUYUL FX Wolf-15 — Journal Metrics Components
// Exports: JournalMetricsCard, JournalTimeline
// Used by: /journal page
// ============================================================

import type { JournalMetrics, DailyJournal, JournalEntry } from "@/types";

// ─── JOURNAL METRICS CARD ─────────────────────────────────────

interface JournalMetricsCardProps {
  metrics: JournalMetrics;
}

export function JournalMetricsCard({ metrics }: JournalMetricsCardProps) {
  const wrColor =
    metrics.win_rate >= 0.6
      ? "var(--green)"
      : metrics.win_rate >= 0.4
      ? "var(--yellow)"
      : "var(--red)";

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.1em",
          color: "var(--text-muted)",
        }}
      >
        JOURNAL METRICS
      </div>

      {/* Win rate gauge */}
      <div style={{ textAlign: "center", padding: "10px 0" }}>
        <div
          className="num"
          style={{
            fontSize: 32,
            fontWeight: 700,
            color: wrColor,
            lineHeight: 1,
          }}
        >
          {Math.round(metrics.win_rate * 100)}%
        </div>
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
          WIN RATE
        </div>
      </div>

      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{
            width: `${metrics.win_rate * 100}%`,
            background: wrColor,
          }}
        />
      </div>

      {/* Stats */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <MetricRow label="Total Trades" value={metrics.total_trades} />
        <MetricRow
          label="Wins / Losses"
          value={`${metrics.total_wins} / ${metrics.total_losses}`}
        />
        <MetricRow
          label="Total PnL"
          value={`${metrics.total_pnl >= 0 ? "+" : ""}${metrics.total_pnl.toFixed(2)}`}
          color={metrics.total_pnl >= 0 ? "var(--green)" : "var(--red)"}
        />
        <MetricRow
          label="Avg RR"
          value={metrics.avg_rr.toFixed(2)}
          color="var(--accent)"
        />
        <MetricRow
          label="Rejection Rate"
          value={`${Math.round(metrics.rejection_rate * 100)}%`}
        />
        {metrics.profit_factor !== undefined && (
          <MetricRow
            label="Profit Factor"
            value={metrics.profit_factor.toFixed(2)}
            color={metrics.profit_factor >= 1.5 ? "var(--green)" : "var(--yellow)"}
          />
        )}
        {metrics.expectancy !== undefined && (
          <MetricRow
            label="Expectancy"
            value={metrics.expectancy.toFixed(2)}
            color={metrics.expectancy > 0 ? "var(--green)" : "var(--red)"}
          />
        )}
        {metrics.best_pair && (
          <MetricRow label="Best Pair" value={metrics.best_pair} color="var(--green)" />
        )}
        {metrics.worst_pair && (
          <MetricRow label="Worst Pair" value={metrics.worst_pair} color="var(--red)" />
        )}
      </div>
    </div>
  );
}

function MetricRow({
  label,
  value,
  color = "var(--text-primary)",
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        fontSize: 11,
      }}
    >
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span className="num" style={{ fontWeight: 600, color }}>
        {value}
      </span>
    </div>
  );
}

// ─── JOURNAL TIMELINE ─────────────────────────────────────────

interface JournalTimelineProps {
  journal: DailyJournal;
}

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
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
          minWidth: 55,
          flexShrink: 0,
        }}
      >
        {new Date(entry.timestamp).toLocaleTimeString("en-US", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        })}
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
