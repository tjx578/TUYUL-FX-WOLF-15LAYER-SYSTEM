"use client";

// ============================================================
// TUYUL FX Wolf-15 — Journal Page (/journal)
// Data: useJournalToday + useJournalWeekly + useJournalMetrics
// ============================================================

import { useState } from "react";
import {
  useJournalToday,
  useJournalWeekly,
  useJournalMetrics,
} from "@/lib/api";
import { JournalMetricsCard, JournalTimeline } from "@/components/JournalMetrics";

export default function JournalPage() {
  const { data: today, isLoading: todayLoading } = useJournalToday();
  const { data: weekly } = useJournalWeekly();
  const { data: metrics } = useJournalMetrics();
  const [view, setView] = useState<"today" | "weekly">("today");

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div>
          <h1
            style={{
              fontSize: 20,
              fontWeight: 700,
              letterSpacing: "0.04em",
              color: "var(--text-primary)",
              margin: 0,
            }}
          >
            TRADING JOURNAL
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            J1-J4 entry logs — wins, losses, rejections
          </p>
        </div>
      </div>

      {/* ── Main grid ── */}
      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 20, alignItems: "start" }}>
        {/* ── Left: metrics card ── */}
        <div>
          {metrics ? (
            <JournalMetricsCard metrics={metrics} />
          ) : (
            <div className="card" style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Loading metrics...
            </div>
          )}
        </div>

        {/* ── Right: journal entries ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Tab selector */}
          <div style={{ display: "flex", gap: 6 }}>
            {(["today", "weekly"] as const).map((v) => (
              <button
                key={v}
                className="btn btn-ghost"
                style={{
                  fontSize: 11,
                  padding: "5px 14px",
                  opacity: view === v ? 1 : 0.5,
                  borderColor: view === v ? "var(--accent)" : "var(--bg-border)",
                  color: view === v ? "var(--accent)" : "var(--text-muted)",
                }}
                onClick={() => setView(v)}
              >
                {v.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Today view */}
          {view === "today" && (
            <div className="panel" style={{ padding: 16 }}>
              {todayLoading ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  Loading today&apos;s journal...
                </div>
              ) : today ? (
                <JournalTimeline journal={today} />
              ) : (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  No journal data for today.
                </div>
              )}
            </div>
          )}

          {/* Weekly view */}
          {view === "weekly" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {(weekly ?? []).length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  No weekly data available.
                </div>
              ) : (
                weekly!.map((day) => (
                  <div key={day.date} className="panel" style={{ padding: 16 }}>
                    {/* Day summary */}
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: 12,
                      }}
                    >
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 700,
                          color: "var(--text-primary)",
                        }}
                      >
                        {day.date}
                      </span>
                      <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
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
                            style={{
                              color:
                                day.metrics.win_rate >= 0.6
                                  ? "var(--green)"
                                  : "var(--yellow)",
                            }}
                          >
                            {Math.round(day.metrics.win_rate * 100)}%
                          </span>
                        </span>
                        <span
                          className="num"
                          style={{
                            color:
                              day.net_pnl >= 0 ? "var(--green)" : "var(--red)",
                            fontWeight: 700,
                          }}
                        >
                          {day.net_pnl >= 0 ? "+" : ""}
                          {day.net_pnl.toFixed(2)}
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
