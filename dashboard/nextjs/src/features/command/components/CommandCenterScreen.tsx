"use client";

// ============================================================
// TUYUL FX Wolf-15 — Command Center Screen
// Extracted from app/(root)/page.tsx → features/command/
// PRD: Global Status Strip, Urgency Rail, Critical Risk Strip,
//      System Health Cluster, Market Context, Event Banner,
//      Quick Actions, Stale Data Banner, Recent Changes
// ============================================================

import { useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCommandCenterState } from "@/hooks/useCommandCenterState";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import DataStreamDiagnostic from "@/components/feedback/DataStreamDiagnostic";
import VerdictEmptyStatePanel from "@/components/feedback/VerdictEmptyStatePanel";
import { VerdictCard } from "@/components/VerdictCard";
import { SystemHealth } from "@/components/SystemHealth";
import GlobalStatusStrip from "@/components/command-center/GlobalStatusStrip";
import UrgencyRail from "@/components/command-center/UrgencyRail";
import StaleDataBanner from "@/components/command-center/StaleDataBanner";
import { useSessionLabel } from "@/hooks/useSessionLabel";
import { formatTime } from "@/lib/timezone";
import type { L12Verdict, Account, FeedStatus } from "@/types";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";

// ── Helpers ──────────────────────────────────────────────────

function statusColor(status: string) {
  if (status === "SAFE" || status === "ok" || status === "OK") return "var(--green)";
  if (status === "WARNING" || status === "WARN") return "var(--yellow)";
  if (status === "CRITICAL" || status === "error") return "var(--red)";
  return "var(--text-muted)";
}

// ── Sub-components (CriticalRiskStrip, EventBanner, KpiCard kept inline — DEBT-03) ──

interface CriticalRiskStripProps {
  breached: { account_id: string; circuit_breaker: boolean; daily_dd_percent?: number; total_dd_percent?: number }[];
  warned: { account_id: string; daily_dd_percent?: number; status?: string }[];
}

function CriticalRiskStrip({ breached, warned }: CriticalRiskStripProps) {
  if (breached.length === 0 && warned.length === 0) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 14px",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border-danger)",
        borderLeft: "3px solid var(--red)",
        background: "rgba(255,61,87,0.05)",
      }}
      role="alert"
      aria-label="Critical risk alerts"
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          fontWeight: 800,
          color: "var(--red)",
          letterSpacing: "0.10em",
        }}
      >
        CRITICAL RISK ALERTS
      </span>

      {breached.map((s) => (
        <div
          key={s.account_id}
          style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 11 }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--red)",
              flexShrink: 0,
              animation: "pulse-dot 1s ease-in-out infinite",
            }}
            aria-hidden="true"
          />
          <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--text-primary)" }}>
            {s.account_id}
          </span>
          {s.circuit_breaker && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 9,
                padding: "2px 7px",
                borderRadius: 3,
                background: "var(--red-glow)",
                color: "var(--red)",
                border: "1px solid var(--border-danger)",
              }}
            >
              CIRCUIT BREAKER
            </span>
          )}
          <span style={{ color: "var(--text-muted)", fontSize: 10 }}>
            DD {s.daily_dd_percent?.toFixed(1) ?? "—"}% daily / {s.total_dd_percent?.toFixed(1) ?? "—"}% total
          </span>
          <Link
            href="/risk"
            style={{
              marginLeft: "auto",
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              color: "var(--red)",
              textDecoration: "none",
            }}
          >
            RISK COMMAND →
          </Link>
        </div>
      ))}

      {warned.map((s) => (
        <div
          key={s.account_id}
          style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 11 }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--yellow)",
              flexShrink: 0,
            }}
            aria-hidden="true"
          />
          <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--text-secondary)" }}>
            {s.account_id}
          </span>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              padding: "2px 7px",
              borderRadius: 3,
              background: "rgba(255,215,64,0.10)",
              color: "var(--yellow)",
              border: "1px solid rgba(255,215,64,0.25)",
            }}
          >
            WARNING
          </span>
          <span style={{ color: "var(--text-muted)", fontSize: 10 }}>
            DD {s.daily_dd_percent?.toFixed(1) ?? "—"}% daily
          </span>
        </div>
      ))}
    </div>
  );
}

interface EventBannerProps {
  blocker: { blocked: boolean; reason?: string; event?: string } | undefined;
}

function EventBanner({ blocker }: EventBannerProps) {
  if (!blocker?.blocked) return null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "9px 14px",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border-warn)",
        borderLeft: "3px solid var(--yellow)",
        background: "rgba(255,215,64,0.05)",
      }}
      role="alert"
      aria-label="News blackout active"
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          fontWeight: 800,
          color: "var(--yellow)",
          letterSpacing: "0.10em",
          flexShrink: 0,
        }}
      >
        NEWS BLACKOUT
      </span>
      <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
        {blocker.reason ?? "High-impact event window active — trading signals are blocked."}
      </span>
      <Link
        href="/news"
        style={{
          marginLeft: "auto",
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          color: "var(--yellow)",
          textDecoration: "none",
          flexShrink: 0,
        }}
      >
        MARKET EVENTS →
      </Link>
    </div>
  );
}

// ── KpiCard ──────────────────────────────────────────────────

interface KpiCardProps {
  label: string;
  value: string | number;
  color: string;
  sub?: string;
  pulse?: boolean;
  href?: string;
}

function KpiCard({ label, value, color, sub, pulse, href }: KpiCardProps) {
  const inner = (
    <div
      className="card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 5,
        padding: "14px 16px",
        position: "relative",
        overflow: "hidden",
        cursor: href ? "pointer" : "default",
        textDecoration: "none",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 2,
          background: color,
          opacity: 0.5,
          borderRadius: "6px 6px 0 0",
        }}
        aria-hidden="true"
      />
      <div
        style={{
          fontSize: 8,
          letterSpacing: "0.12em",
          color: "var(--text-muted)",
          fontWeight: 700,
          fontFamily: "var(--font-mono)",
        }}
      >
        {label}
      </div>
      <div
        className="num"
        style={{
          fontSize: 26,
          fontWeight: 700,
          color,
          lineHeight: 1,
          animation: pulse ? "pulse-dot 1.5s ease-in-out infinite" : undefined,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 1 }}>
          {sub}
        </div>
      )}
    </div>
  );
  return href ? (
    <Link href={href} style={{ textDecoration: "none" }}>
      {inner}
    </Link>
  ) : (
    inner
  );
}

// ── Main Screen ─────────────────────────────────────────────

export function CommandCenterScreen() {
  const {
    verdictList,
    activeTrades,
    accounts,
    snapshotList,
    context,
    execution,
    health,
    orchestrator,
    calendarBlocker,
    recentAlerts,
    topActionableSignals,
    executeCount,
    highConfidence,
    criticalSnapshots,
    warnSnapshots,
    isSystemDegraded,
    isStale,
    wsStatus,
    dataErrors,
    verdictEmptyState,
    vLoading,
  } = useCommandCenterState();

  const [selectedVerdict, setSelectedVerdict] = useState<L12Verdict | null>(null);
  const liveSession = useSessionLabel();
  const router = useRouter();

  // GAP-02: Navigate to Signal Board with signal pre-selected (single take-signal flow)
  const handleTakeFromRail = useCallback((verdict: L12Verdict) => {
    const signalRef = `${verdict.symbol}_${verdict.timestamp ?? ""}`;
    router.push(`/signals?select=${encodeURIComponent(signalRef)}`);
  }, [router]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <PageComplianceBanner page="dashboard" />

      {/* ── Page header ── */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
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
            COMMAND CENTER
          </h1>
          <p
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              marginTop: 3,
              margin: 0,
            }}
          >
            Live signal + risk state — Wolf-15 system
          </p>
        </div>
      </div>

      {/* 1. Global Status Strip */}
      <GlobalStatusStrip
        health={health}
        wsStatus={wsStatus as WsConnectionStatus}
        mode={isSystemDegraded ? "DEGRADED" : "NORMAL"}
        executionState={execution?.state}
        openTradeCount={activeTrades.length}
        isStale={isStale}
      />

      {/* 2. Stale / degraded banner */}
      <StaleDataBanner
        isStale={isStale}
        isSystemDegraded={isSystemDegraded}
        wsStatus={wsStatus}
        dataErrors={dataErrors}
        feedStatus={health?.feed_status}
        feedDetail={health?.detail}
      />

      {/* 3. Event Banner — high-impact news blackout */}
      <EventBanner
        blocker={
          calendarBlocker
            ? {
              blocked: calendarBlocker.is_locked,
              reason: calendarBlocker.lock_reason,
              event:
                calendarBlocker.upcoming?.[0]?.event ??
                calendarBlocker.upcoming?.[0]?.title,
            }
            : undefined
        }
      />

      {/* 4. Critical Risk Strip */}
      <CriticalRiskStrip breached={criticalSnapshots} warned={warnSnapshots} />

      {/* 5. Data stream diagnostic */}
      {dataErrors.length > 0 && (
        <DataStreamDiagnostic
          failedStreams={dataErrors}
          allStreams={[
            "verdicts",
            "trades",
            "context",
            "execution",
            "accounts",
            "risk",
          ]}
        />
      )}

      {/* 6. Urgency Rail — top 3 actionable signals → navigates to Signal Board */}
      <UrgencyRail
        signals={topActionableSignals}
        accounts={accounts}
        onTake={handleTakeFromRail}
      />

      {/* 7. KPI bar */}
      <div className="overview-kpi-grid">
        <KpiCard
          label="ACTIONABLE SIGNALS"
          value={executeCount}
          color={executeCount > 0 ? "var(--accent)" : "var(--text-muted)"}
          sub={`of ${verdictList.length} pairs`}
          pulse={executeCount > 0}
          href="/signals"
        />
        <KpiCard
          label="OPEN TRADES"
          value={activeTrades.length}
          color={activeTrades.length > 0 ? "var(--green)" : "var(--text-muted)"}
          sub="live positions"
          href="/trades"
        />
        <KpiCard
          label="HIGH CONFIDENCE"
          value={highConfidence}
          color={highConfidence > 0 ? "var(--cyan)" : "var(--text-muted)"}
          sub="conf >= 75%"
          href="/signals"
        />
        <KpiCard
          label="ENGINE STATE"
          value={execution?.state ?? "—"}
          color={
            execution?.state === "SIGNAL_READY" ? "var(--accent)" :
              execution?.state === "EXECUTING" ? "var(--green)" :
                execution?.state === "SCANNING" ? "var(--blue)" :
                  "var(--text-muted)"
          }
          sub={
            execution
              ? `${execution.signal_count ?? 0} signals today`
              : "no data"
          }
        />
        <KpiCard
          label="ORCHESTRATOR"
          value={orchestrator?.orchestrator_ready ? "READY" : (orchestrator?.mode ?? "UNKNOWN")}
          color={
            orchestrator?.orchestrator_ready
              ? "var(--green)"
              : orchestrator?.mode === "SAFE"
                ? "var(--yellow)"
                : "var(--red)"
          }
          sub={
            orchestrator?.orchestrator_heartbeat_age_seconds !== undefined &&
              orchestrator?.orchestrator_heartbeat_age_seconds !== null
              ? `hb ${Math.round(orchestrator.orchestrator_heartbeat_age_seconds)}s`
              : "heartbeat n/a"
          }
        />
      </div>

      {/* 8. Main grid: verdicts left, system right */}
      <div className="overview-main-grid">
        {/* Left: signal universe */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.12em",
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            SIGNAL UNIVERSE
            {vLoading && (
              <span style={{ fontSize: 9, color: "var(--text-faint)", fontWeight: 400 }}>
                LOADING...
              </span>
            )}
            {isStale && !vLoading && (
              <span
                style={{
                  fontSize: 9,
                  color: "var(--yellow)",
                  fontWeight: 700,
                  fontFamily: "var(--font-mono)",
                  padding: "1px 5px",
                  borderRadius: 3,
                  background: "rgba(255,215,64,0.08)",
                }}
              >
                STALE
              </span>
            )}
            <span
              className="badge badge-blue"
              style={{ marginLeft: "auto", fontSize: 9 }}
            >
              {verdictList.length} PAIRS
            </span>
            {context?.session && (
              <span className="badge badge-cyan" style={{ fontSize: 9 }}>
                {liveSession}
              </span>
            )}
          </div>

          {vLoading ? (
            <div className="overview-verdict-grid">
              {Array.from({ length: 6 }).map((_, idx) => (
                <div
                  key={`skeleton-${idx}`}
                  className="skeleton card"
                  style={{ minHeight: 160 }}
                  aria-label="Loading verdict card"
                />
              ))}
            </div>
          ) : verdictList.length === 0 ? (
            <VerdictEmptyStatePanel state={verdictEmptyState} />
          ) : (
            <div className="overview-verdict-grid">
              {verdictList.map((v: L12Verdict) => (
                <VerdictCard
                  key={`${v.symbol}-${v.timestamp}`}
                  verdict={v}
                  selected={selectedVerdict?.symbol === v.symbol}
                  onTake={() => handleTakeFromRail(v)}
                  onSkip={() => setSelectedVerdict(null)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right: system health + context + alerts + quick actions */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* System Health */}
          <SystemHealth />

          {/* Market Context */}
          {context && (
            <div
              className="panel"
              style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}
            >
              <div
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  color: "var(--text-muted)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                MARKET CONTEXT
              </div>
              {(
                [
                  { label: "SESSION", value: liveSession },
                  { label: "REGIME", value: context.regime },
                  { label: "VOLATILITY", value: context.volatility },
                  { label: "TREND", value: context.trend },
                ] as const
              ).map(({ label, value }) =>
                value ? (
                  <div
                    key={label}
                    style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}
                  >
                    <span style={{ color: "var(--text-muted)" }}>{label}</span>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-secondary)",
                        fontWeight: 700,
                      }}
                    >
                      {value}
                    </span>
                  </div>
                ) : null
              )}
            </div>
          )}

          {/* Account Readiness Summary */}
          {accounts.length > 0 && (
            <div
              className="panel"
              style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}
            >
              <div
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  color: "var(--text-muted)",
                  fontFamily: "var(--font-mono)",
                  marginBottom: 2,
                }}
              >
                ACCOUNT READINESS
              </div>
              {accounts.slice(0, 4).map((acc: Account) => {
                const snap = snapshotList.find((s) => s.account_id === acc.id);
                const ready = !snap || (snap.status === "SAFE" && !snap.circuit_breaker);
                return (
                  <div
                    key={acc.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      fontSize: 11,
                    }}
                  >
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        background: ready ? "var(--green)" : "var(--red)",
                        flexShrink: 0,
                      }}
                      aria-hidden="true"
                    />
                    <span
                      style={{
                        flex: 1,
                        color: "var(--text-secondary)",
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {acc.account_name ?? acc.id}
                    </span>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 9,
                        color: ready ? "var(--green)" : "var(--red)",
                        fontWeight: 700,
                      }}
                    >
                      {ready ? "READY" : snap?.status ?? "BLOCKED"}
                    </span>
                  </div>
                );
              })}
              {accounts.length > 4 && (
                <Link
                  href="/accounts"
                  style={{
                    fontSize: 10,
                    color: "var(--text-muted)",
                    fontFamily: "var(--font-mono)",
                    textDecoration: "none",
                  }}
                >
                  +{accounts.length - 4} more → CAPITAL ACCOUNTS
                </Link>
              )}
            </div>
          )}

          {/* Recent alerts */}
          {recentAlerts.length > 0 && (
            <div
              className="panel"
              style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 6 }}
            >
              <div
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  color: "var(--text-muted)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                RECENT ALERTS
              </div>
              {recentAlerts.map((a, idx) => {
                let text: string;
                if (typeof a === "string") {
                  text = a;
                } else {
                  text = (a as { message?: string }).message ?? JSON.stringify(a);
                }
                const MAX_ALERT_LEN = 300;
                if (text.length > MAX_ALERT_LEN) {
                  text = text.slice(0, MAX_ALERT_LEN) + "…";
                }
                return (
                  <div
                    key={idx}
                    style={{
                      fontSize: 11,
                      color: "var(--text-secondary)",
                      borderLeft: "2px solid var(--border-default)",
                      paddingLeft: 8,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {text}
                  </div>
                );
              })}
            </div>
          )}

          {/* Quick actions */}
          <div
            className="panel"
            style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}
          >
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.12em",
                color: "var(--text-muted)",
                fontFamily: "var(--font-mono)",
                marginBottom: 2,
              }}
            >
              QUICK ACTIONS
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <Link
                href="/signals"
                style={{
                  display: "block",
                  padding: "8px 12px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--accent)",
                  background: "rgba(0,229,255,0.05)",
                  color: "var(--accent)",
                  fontSize: 11,
                  fontWeight: 700,
                  fontFamily: "var(--font-mono)",
                  textDecoration: "none",
                  textAlign: "center",
                  letterSpacing: "0.04em",
                }}
              >
                OPEN SIGNAL BOARD
              </Link>
              <Link
                href="/risk"
                style={{
                  display: "block",
                  padding: "8px 12px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border-default)",
                  color: "var(--text-secondary)",
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: "var(--font-mono)",
                  textDecoration: "none",
                  textAlign: "center",
                  letterSpacing: "0.04em",
                }}
              >
                RISK COMMAND
              </Link>
              <Link
                href="/trades"
                style={{
                  display: "block",
                  padding: "8px 12px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border-default)",
                  color: "var(--text-secondary)",
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: "var(--font-mono)",
                  textDecoration: "none",
                  textAlign: "center",
                  letterSpacing: "0.04em",
                }}
              >
                TRADE DESK
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* TakeSignalForm removed (GAP-02) — signals are now taken from Signal Board */}
    </div>
  );
}
