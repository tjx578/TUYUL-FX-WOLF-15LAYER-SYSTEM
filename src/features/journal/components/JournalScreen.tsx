"use client";

import { useMemo, useState } from "react";
import { useJournalToday, useJournalWeekly, useJournalMetrics } from "../api/journal.api";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { JournalMetricsCard } from "./JournalMetricsCard";
import { JournalTimeline } from "./JournalTimeline";
import { JournalKpiStrip } from "./JournalKpiStrip";
import { JournalWeeklyDay } from "./JournalWeeklyDay";
import { useJournalFocusContract } from "../hooks/useJournalFocusContract";
import { DomainHeader } from "@/shared/ui/DomainHeader";
import { JournalBridgeBanner } from "./JournalBridgeBanner";
import { useJournalContextFilter } from "../hooks/useJournalContextFilter";

export function JournalScreen() {
  const { data: today, isLoading: todayLoading } = useJournalToday();
  const { data: weekly, isLoading: weeklyLoading } = useJournalWeekly();
  const { data: metrics } = useJournalMetrics();

  const [view, setView] = useState<"today" | "weekly">("today");

  const focus = useJournalFocusContract();

  const focusFilter = useMemo(
    () => (focus ? { accountId: focus.accountId, signalId: focus.signalId } : null),
    [focus],
  );

  const filteredTodayEntries = useJournalContextFilter(
    today?.entries ?? [],
    focusFilter,
  );

  const filteredWeekly = useMemo(() => {
    if (!weekly || !focusFilter?.accountId && !focusFilter?.signalId) return weekly ?? [];

    return weekly.map((day) => ({
      ...day,
      entries: day.entries.filter((entry: { account_id?: string; signal_id?: string }) => {
        const accountOk = focusFilter.accountId ? entry.account_id === focusFilter.accountId : true;
        const signalOk = focusFilter.signalId ? entry.signal_id === focusFilter.signalId : true;
        return accountOk && signalOk;
      }),
    }));
  }, [weekly, focusFilter]);

  const todayView = today
    ? {
      ...today,
      entries: filteredTodayEntries,
    }
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="journal" />

      <DomainHeader
        domain="journal"
        title="TRADING JOURNAL"
        subtitle="J1-J4 entry logs — wins, losses, rejections, compliance trace"
      />

      <JournalBridgeBanner focus={focus} />

      {metrics && <JournalKpiStrip metrics={metrics} />}

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 20, alignItems: "start" }}>
        <div>
          {metrics ? (
            <JournalMetricsCard metrics={metrics} />
          ) : (
            <div className="skeleton card" style={{ height: 280 }} aria-label="Loading metrics" />
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", gap: 6 }}>
            {(["today", "weekly"] as const).map((v) => (
              <button
                key={v}
                className="btn btn-ghost"
                style={{
                  fontSize: 11,
                  padding: "5px 14px",
                  borderColor: view === v ? "var(--accent)" : "var(--border-default)",
                  color: view === v ? "var(--accent)" : "var(--text-muted)",
                  background: view === v ? "var(--accent-muted)" : "transparent",
                }}
                onClick={() => setView(v)}
                aria-pressed={view === v}
              >
                {v.toUpperCase()}
              </button>
            ))}
          </div>

          {view === "today" && (
            <div className="panel" style={{ padding: 16 }}>
              {todayLoading ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="skeleton" style={{ height: 52, borderRadius: "var(--radius-sm)" }} />
                  ))}
                </div>
              ) : todayView ? (
                <JournalTimeline journal={todayView} />
              ) : (
                <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "20px 0", textAlign: "center" }}>
                  No journal data for today.
                </div>
              )}
            </div>
          )}

          {view === "weekly" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {weeklyLoading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="skeleton panel" style={{ height: 100 }} />
                ))
              ) : filteredWeekly.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "20px 0", textAlign: "center" }}>
                  No weekly data available.
                </div>
              ) : (
                filteredWeekly.map((day) => (
                  <JournalWeeklyDay key={day.date} day={day} />
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
