"use client";

// ============================================================
// TUYUL FX Wolf-15 — Trading Journal (/journal)
// Production: metrics card, today/weekly timeline,
//   win-rate, PnL, J-type badges
// ============================================================

import { useState } from "react";
import { useJournalToday, useJournalWeekly, useJournalMetrics } from "@/lib/api";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { JournalMetricsCard, JournalTimeline } from "@/components/JournalMetrics";

// ── Summary KPI ───────────────────────────────────────────────

function JournalKpi({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="card" style={{ padding: "11px 14px", display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--text-muted)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
        {label}
      </div>
      <div className="num" style={{ fontSize: 20, fontWeight: 700, color: color ?? "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────

export default function JournalPage() {
  const { data: today,   isLoading: todayLoading } = useJournalToday();
  const { data: weekly,  isLoading: weeklyLoading } = useJournalWeekly();
  const { data: metrics } = useJournalMetrics();
  const [view, setView] = useState<"today" | "weekly">("today");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="journal" />

      {/* ── Header ── */}
      <div>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 800,
            letterSpacing: "0.06em",
            color: "var(--text-primary)",
            margin: 0,
            fontFamily: "var(--font-display)",
          }}
        >
          TRADING JOURNAL
        </h1>
        <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
          J1-J4 entry logs — wins, losses, rejections, compliance trace
        </p>
      </div>

      {/* ── KPI summary from metrics ── */}
      {metrics && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12 }}>
          <JournalKpi
            label="WIN RATE"
            value={`${Math.round(metrics.win_rate * 100)}%`}
            color={metrics.win_rate >= 0.6 ? "var(--green)" : metrics.win_rate >= 0.4 ? "var(--yellow)" : "var(--red)"}
          />
          <JournalKpi
            label="TOTAL PNL"
            value={`${metrics.total_pnl >= 0 ? "+" : ""}${metrics.total_pnl.toFixed(2)}`}
            color={metrics.total_pnl >= 0 ? "var(--green)" : "var(--red)"}
          />
          <JournalKpi
            label="AVG R:R"
            value={metrics.avg_rr?.toFixed(2) ?? "—"}
            color={metrics.avg_rr >= 2 ? "var(--green)" : metrics.avg_rr >= 1.5 ? "var(--accent)" : "var(--yellow)"}
          />
          <JournalKpi
            label="PROFIT FACTOR"
            value={metrics.profit_factor?.toFixed(2) ?? "—"}
            color={(metrics.profit_factor ?? 0) >= 1.5 ? "var(--green)" : "var(--yellow)"}
          />
        </div>
      )}

      {/* ── Main layout ── */}
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 20, alignItems: "start" }}>
        {/* ── Left: metrics card ── */}
        <div>
          {metrics ? (
            <JournalMetricsCard metrics={metrics} />
          ) : (
            <div className="skeleton card" style={{ height: 280 }} aria-label="Loading metrics" />
          )}
        </div>

        {/* ── Right: journal entries ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* View tabs */}
          <div style={{ display: "flex", gap: 6 }}>
            {(["today", "weekly"] as const).map((v) => (
              <button
                key={v}
                className="btn btn-ghost"
                style={{
                  fontSize: 11,
                  padding: "5px 14px",
                  borderColor: view === v ? "var(--accent)" : "var(--border-default)",
                  color:       view === v ? "var(--accent)" : "var(--text-muted)",
                  background:  view === v ? "var(--accent-muted)" : "transparent",
                }}
                onClick={() => setView(v)}
                aria-pressed={view === v}
              >
                {v.toUpperCase()}
              </button>
            ))}
          </div>

          {/* TODAY view */}
          {view === "today" && (
            <div className="panel" style={{ padding: 16 }}>
              {todayLoading ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="skeleton" style={{ height: 52, borderRadius: "var(--radius-sm)" }} />
                  ))}
                </div>
              ) : today ? (
                <JournalTimeline journal={today} />
              ) : (
                <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "20px 0", textAlign: "center" }}>
                  No journal data for today.
                </div>
              )}
            </div>
          )}

          {/* WEEKLY view */}
          {view === "weekly" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {weeklyLoading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="skeleton panel" style={{ height: 100 }} />
                ))
              ) : (weekly ?? []).length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "20px 0", textAlign: "center" }}>
                  No weekly data available.
                </div>
              ) : (
                weekly!.map((day) => (
                  <div key={day.date} className="panel" style={{ padding: 16 }}>
                    {/* Day header */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
                        {day.date}
                      </span>
                      <div style={{ display: "flex", gap: 12, fontSize: 11, alignItems: "center" }}>
                        <span style={{ color: "var(--text-muted)" }}>
                          Trades:{" "}
                          <span className="num" style={{ color: "var(--text-secondary)" }}>
                            {day.metrics.total_trades}
                          </span>
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
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
