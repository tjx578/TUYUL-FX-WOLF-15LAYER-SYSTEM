"use client";

// ============================================================
// TUYUL FX Wolf-15 — News / Calendar Page (/news)
// Features: impact badges, news lock banner, countdown,
//   source health, currency filter
// ============================================================

import { useMemo, useState } from "react";
import { useCalendarEvents, useCalendarBlocker, useCalendarSourceHealth } from "@/lib/api";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import type { CalendarEvent } from "@/types";

// ── Impact badge ──────────────────────────────────────────────

const IMPACT_STYLE: Record<string, { bg: string; color: string; cls: string }> = {
  HIGH: { bg: "var(--red-glow)", color: "var(--red)", cls: "badge-red" },
  MEDIUM: { bg: "var(--yellow-glow)", color: "var(--yellow)", cls: "badge-yellow" },
  LOW: { bg: "rgba(68,138,255,0.12)", color: "var(--blue)", cls: "badge-blue" },
};

function ImpactBadge({ impact }: { impact: string }) {
  const s = IMPACT_STYLE[impact] ?? IMPACT_STYLE.LOW;
  return <span className={`badge ${s.cls}`}>{impact}</span>;
}

// ── Event row ─────────────────────────────────────────────────

function EventRow({ event, idx }: { event: CalendarEvent; idx: number }) {
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

// ── News lock banner ──────────────────────────────────────────

function NewsLockBanner({ reason }: { reason?: string }) {
  return (
    <div
      role="alert"
      className="kill-banner panel"
      style={{
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        borderColor: "var(--border-danger)",
        background: "var(--red-glow)",
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: "var(--red)",
          display: "inline-block",
          animation: "pulse-dot 1.2s ease-in-out infinite",
          flexShrink: 0,
        }}
      />
      <div>
        <div style={{ fontFamily: "var(--font-display)", fontSize: 12, fontWeight: 800, color: "var(--red)", letterSpacing: "0.06em" }}>
          NEWS LOCK ACTIVE — TRADING RESTRICTED
        </div>
        {reason && (
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{reason}</div>
        )}
      </div>
    </div>
  );
}

// ── Source health dot ─────────────────────────────────────────

function SourceHealth() {
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

// ── Main page ─────────────────────────────────────────────────

const IMPACT_FILTERS = ["ALL", "HIGH", "MEDIUM", "LOW"] as const;
const CURRENCY_FILTER_OPTS = ["ALL", "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"];

export default function NewsPage() {
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

      {/* ── Header ── */}
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

      {/* ── News lock banner ── */}
      {blocker?.is_locked && <NewsLockBanner reason={blocker.lock_reason} />}

      {/* ── Controls row ── */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        {/* Period tabs */}
        <div style={{ display: "flex", gap: 4 }}>
          {(["today", "upcoming"] as const).map((p) => (
            <button
              key={p}
              className="btn btn-ghost"
              style={{
                fontSize: 10,
                padding: "5px 13px",
                borderColor: period === p ? "var(--accent)" : "var(--border-default)",
                color: period === p ? "var(--accent)" : "var(--text-muted)",
                background: period === p ? "var(--accent-muted)" : "transparent",
              }}
              onClick={() => setPeriod(p)}
              aria-pressed={period === p}
            >
              {p.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Impact filter */}
        <div style={{ display: "flex", gap: 4 }}>
          {IMPACT_FILTERS.map((f) => (
            <button
              key={f}
              className="btn btn-ghost"
              style={{
                fontSize: 10,
                padding: "5px 11px",
                borderColor: impactFilter === f ? (IMPACT_STYLE[f]?.color ?? "var(--border-strong)") : "var(--border-default)",
                color: impactFilter === f ? (IMPACT_STYLE[f]?.color ?? "var(--text-primary)") : "var(--text-muted)",
              }}
              onClick={() => setImpactFilter(f)}
              aria-pressed={impactFilter === f}
            >
              {f}
            </button>
          ))}
        </div>

        {/* Currency filter */}
        <select
          value={currencyFilter}
          onChange={(e) => setCurrencyFilter(e.target.value)}
          style={{ fontSize: 11, padding: "5px 10px" }}
          aria-label="Filter by currency"
        >
          {CURRENCY_FILTER_OPTS.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>

        {/* Event count badges */}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {highCount > 0 && (
            <span className="badge badge-red">{highCount} HIGH</span>
          )}
          {mediumCount > 0 && (
            <span className="badge badge-yellow">{mediumCount} MED</span>
          )}
          <span className="badge badge-muted">{filtered.length} total</span>
        </div>
      </div>

      {/* ── Upcoming events from blocker ── */}
      {blocker && blocker.upcoming_count > 0 && !blocker.is_locked && (
        <div
          className="panel"
          style={{
            padding: "10px 14px",
            borderColor: "var(--border-warn)",
            background: "var(--yellow-glow)",
            display: "flex",
            alignItems: "center",
            gap: 10,
            fontSize: 11,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--yellow)",
              display: "inline-block",
              animation: "pulse-dot 1.5s ease-in-out infinite",
              flexShrink: 0,
            }}
          />
          <span style={{ color: "var(--yellow)", fontWeight: 700 }}>
            {blocker.upcoming_count} upcoming high-impact event{blocker.upcoming_count > 1 ? "s" : ""}
          </span>
          <span style={{ color: "var(--text-muted)" }}>— monitor news lock window.</span>
        </div>
      )}

      {/* ── Table ── */}
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
                <EventRow key={event.id ?? idx} event={event} idx={idx} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
