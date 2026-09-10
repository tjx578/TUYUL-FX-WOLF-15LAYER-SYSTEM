"use client";

// ============================================================
// TUYUL FX Wolf-15 — ExplorerFiltersBar
// Research surface filter bar: verdict, session, sort, search
// ============================================================

import type {
  ExplorerFilters,
  ExplorerVerdictFilter,
  ExplorerSessionFilter,
  ExplorerSortKey,
} from "@/hooks/useSignalExplorerState";

interface ExplorerFiltersBarProps {
  filters: ExplorerFilters;
  counts: { total: number; execute: number; hold: number; noTrade: number; abort: number; filtered: number };
  compareMode: boolean;
  onQueryChange: (q: string) => void;
  onVerdictFilter: (f: ExplorerVerdictFilter) => void;
  onSessionFilter: (f: ExplorerSessionFilter) => void;
  onSortKey: (k: ExplorerSortKey) => void;
  onToggleSortDir: () => void;
  onToggleGateFilter: () => void;
  onReset: () => void;
  onToggleCompareMode: () => void;
}

const VERDICT_OPTS: { value: ExplorerVerdictFilter; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "EXECUTE", label: "Execute" },
  { value: "HOLD", label: "Hold" },
  { value: "NO_TRADE", label: "No Trade" },
  { value: "ABORT", label: "Abort" },
];

const SESSION_OPTS: { value: ExplorerSessionFilter; label: string }[] = [
  { value: "ALL", label: "All Sessions" },
  { value: "LONDON", label: "London" },
  { value: "NEW_YORK", label: "New York" },
  { value: "ASIA", label: "Asia" },
  { value: "OVERLAP", label: "Overlap" },
];

const SORT_OPTS: { value: ExplorerSortKey; label: string }[] = [
  { value: "confidence", label: "Confidence" },
  { value: "rr", label: "R:R" },
  { value: "wolf", label: "Wolf" },
  { value: "tii", label: "TII" },
  { value: "frpc", label: "FRPC" },
  { value: "timestamp", label: "Time" },
];

export function ExplorerFiltersBar({
  filters,
  counts,
  compareMode,
  onQueryChange,
  onVerdictFilter,
  onSessionFilter,
  onSortKey,
  onToggleSortDir,
  onToggleGateFilter,
  onReset,
  onToggleCompareMode,
}: ExplorerFiltersBarProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: "14px 16px",
        background: "var(--bg-card)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-lg)",
      }}
    >
      {/* Row 1: search + compare toggle + reset */}
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <div style={{ position: "relative", flex: 1, maxWidth: 280 }}>
          <span
            style={{
              position: "absolute",
              left: 10,
              top: "50%",
              transform: "translateY(-50%)",
              fontSize: 12,
              color: "var(--text-muted)",
              pointerEvents: "none",
            }}
          >
            ⌕
          </span>
          <input
            value={filters.query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Search pair (EURUSD)…"
            style={{
              width: "100%",
              padding: "8px 10px 8px 28px",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-strong)",
              background: "var(--bg-elevated)",
              color: "var(--text-primary)",
              fontSize: 12,
              fontFamily: "var(--font-body)",
              outline: "none",
            }}
          />
        </div>

        {/* Sort key */}
        <select
          value={filters.sortKey}
          onChange={(e) => onSortKey(e.target.value as ExplorerSortKey)}
          style={{
            padding: "8px 10px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-strong)",
            background: "var(--bg-elevated)",
            color: "var(--text-secondary)",
            fontSize: 11,
            cursor: "pointer",
          }}
        >
          {SORT_OPTS.map((o) => (
            <option key={o.value} value={o.value}>Sort: {o.label}</option>
          ))}
        </select>

        {/* Sort dir */}
        <button
          onClick={onToggleSortDir}
          title="Toggle sort direction"
          style={{
            padding: "8px 10px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-strong)",
            background: "var(--bg-elevated)",
            color: "var(--text-secondary)",
            fontSize: 12,
            cursor: "pointer",
            minWidth: 34,
          }}
        >
          {filters.sortDir === "desc" ? "↓" : "↑"}
        </button>

        {/* Gate filter */}
        <button
          onClick={onToggleGateFilter}
          style={{
            padding: "8px 10px",
            borderRadius: "var(--radius-md)",
            border: `1px solid ${filters.showOnlyGatesPassed ? "var(--border-accent)" : "var(--border-strong)"}`,
            background: filters.showOnlyGatesPassed ? "var(--accent-muted)" : "var(--bg-elevated)",
            color: filters.showOnlyGatesPassed ? "var(--accent)" : "var(--text-muted)",
            fontSize: 11,
            letterSpacing: "0.06em",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          Gates All Passed
        </button>

        {/* Compare mode */}
        <button
          onClick={onToggleCompareMode}
          style={{
            padding: "8px 12px",
            borderRadius: "var(--radius-md)",
            border: `1px solid ${compareMode ? "var(--border-accent)" : "var(--border-strong)"}`,
            background: compareMode ? "var(--accent)" : "var(--bg-elevated)",
            color: compareMode ? "#fff" : "var(--text-muted)",
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "0.06em",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          Compare {compareMode ? "ON" : "OFF"}
        </button>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          <span className="badge badge-blue" style={{ fontSize: 9 }}>
            {counts.filtered}/{counts.total}
          </span>
          {counts.execute > 0 && (
            <span className="badge badge-success" style={{ fontSize: 9 }}>
              {counts.execute} EXEC
            </span>
          )}
          <button
            onClick={onReset}
            style={{
              padding: "6px 10px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border-strong)",
              background: "transparent",
              color: "var(--text-muted)",
              fontSize: 10,
              cursor: "pointer",
              letterSpacing: "0.06em",
            }}
          >
            Reset
          </button>
        </div>
      </div>

      {/* Row 2: verdict tabs + session filter */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {/* Verdict pills */}
        <div style={{ display: "flex", gap: 4 }}>
          {VERDICT_OPTS.map((o) => {
            const active = filters.verdictFilter === o.value;
            return (
              <button
                key={o.value}
                onClick={() => onVerdictFilter(o.value)}
                style={{
                  padding: "5px 10px",
                  borderRadius: "var(--radius-sm)",
                  border: `1px solid ${active ? "var(--border-accent)" : "var(--border-subtle)"}`,
                  background: active ? "var(--accent-muted)" : "transparent",
                  color: active ? "var(--accent)" : "var(--text-muted)",
                  fontSize: 10,
                  fontWeight: active ? 700 : 400,
                  letterSpacing: "0.07em",
                  cursor: "pointer",
                }}
              >
                {o.label.toUpperCase()}
              </button>
            );
          })}
        </div>

        <div style={{ width: 1, height: 18, background: "var(--border-default)", margin: "0 4px" }} />

        {/* Session pills */}
        <div style={{ display: "flex", gap: 4 }}>
          {SESSION_OPTS.map((o) => {
            const active = filters.sessionFilter === o.value;
            return (
              <button
                key={o.value}
                onClick={() => onSessionFilter(o.value)}
                style={{
                  padding: "5px 10px",
                  borderRadius: "var(--radius-sm)",
                  border: `1px solid ${active ? "rgba(0,212,255,0.35)" : "var(--border-subtle)"}`,
                  background: active ? "rgba(0,212,255,0.08)" : "transparent",
                  color: active ? "var(--cyan)" : "var(--text-muted)",
                  fontSize: 10,
                  fontWeight: active ? 700 : 400,
                  letterSpacing: "0.07em",
                  cursor: "pointer",
                }}
              >
                {o.label.toUpperCase()}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
