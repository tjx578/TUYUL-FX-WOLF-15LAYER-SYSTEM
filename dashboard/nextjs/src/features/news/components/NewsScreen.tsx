"use client";

import { useMemo, useState } from "react";
import { useCalendarEvents, useCalendarBlocker } from "../api/calendar.api";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import type { CalendarEvent } from "@/types";
import { SourceHealth } from "./SourceHealth";
import { NewsLockBanner } from "./NewsLockBanner";
import { NewsFilterBar } from "./NewsFilterBar";
import { UpcomingAlert } from "./UpcomingAlert";
import { EventRow } from "./EventRow";

export function NewsScreen() {
  const [impactFilter, setImpactFilter] = useState<string>("ALL");
  const [currencyFilter, setCurrencyFilter] = useState<string>("ALL");
  const [period, setPeriod] = useState<"today" | "upcoming">("today");

  const { data, isLoading } = useCalendarEvents(
    period,
    impactFilter !== "ALL" ? impactFilter : undefined
  );
  const { data: blocker } = useCalendarBlocker();

  const filtered = useMemo(() => {
    if (!data) return [];
    if (currencyFilter === "ALL") return data;
    return data.filter((e: CalendarEvent) => e.currency === currencyFilter);
  }, [data, currencyFilter]);

  const { highCount, mediumCount } = useMemo(() => ({
    highCount: filtered.filter((e) => e.impact === "HIGH").length,
    mediumCount: filtered.filter((e) => e.impact === "MEDIUM").length,
  }), [filtered]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="news" />

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
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
            NEWS CALENDAR
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            Economic events — HIGH impact governs news lock
          </p>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <SourceHealth />
        </div>
      </div>

      {blocker?.is_locked && <NewsLockBanner reason={blocker.lock_reason} />}

      <NewsFilterBar
        period={period}
        setPeriod={setPeriod}
        impactFilter={impactFilter}
        setImpactFilter={setImpactFilter}
        currencyFilter={currencyFilter}
        setCurrencyFilter={setCurrencyFilter}
        highCount={highCount}
        mediumCount={mediumCount}
        totalCount={filtered.length}
      />

      {blocker && <UpcomingAlert blocker={blocker} />}

      {/* Table */}
      {isLoading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }} aria-busy="true">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 40, borderRadius: "var(--radius-sm)" }} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div
          className="panel"
          style={{ padding: "32px 20px", textAlign: "center", fontSize: 12, color: "var(--text-muted)" }}
        >
          No calendar events for the selected filters.
        </div>
      ) : (
        <div
          style={{
            overflowX: "auto",
            borderRadius: "var(--radius-lg)",
            border: "1px solid var(--border-default)",
          }}
          role="region"
          aria-label="News calendar table"
        >
          <table>
            <thead>
              <tr>
                {["TIME", "CCY", "IMPACT", "EVENT", "PREV / FORE / ACTUAL"].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((event: CalendarEvent, idx) => (
                <EventRow key={event.id ?? idx} event={event} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
