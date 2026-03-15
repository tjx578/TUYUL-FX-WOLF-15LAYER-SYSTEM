"use client";

// ============================================================
// TUYUL FX Wolf-15 — Command Center (/)
// PRD: Global Status Strip, Urgency Rail, Critical Risk Strip,
//      System Health Cluster, Market Context, Event Banner,
//      Quick Actions, Kill Switch
// ============================================================

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  useAllVerdicts,
  useActiveTrades,
  useContext,
  useExecution,
  useAccounts,
  useAccountsRiskSnapshot,
  useHealth,
  useCalendarBlocker,
  type ActiveTradesResponse,
  type AccountRiskSnapshot,
} from "@/lib/api";
import { TakeSignalForm } from "@/components/TakeSignalForm";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import DataStreamDiagnostic from "@/components/feedback/DataStreamDiagnostic";
import { VerdictCard } from "@/components/VerdictCard";
import { SystemHealth } from "@/components/SystemHealth";
import { useAlertsWS } from "@/lib/websocket";
import { useSystemStore } from "@/store/useSystemStore";
import type { L12Verdict, Trade, Account } from "@/types";

// ── Helpers ──────────────────────────────────────────────────

function statusColor(status: string) {
  if (status === "SAFE" || status === "ok" || status === "OK") return "var(--green)";
  if (status === "WARNING" || status === "WARN") return "var(--yellow)";
  if (status === "CRITICAL" || status === "error") return "var(--red)";
  return "var(--text-muted)";
}

function verdictIsActionable(v: L12Verdict): boolean {
  return (
    String(v.verdict ?? "").startsWith("EXECUTE") &&
    !v.blocked &&
    !v.expired
  );
}

function urgencyScore(v: L12Verdict): number {
  const conf = v.confidence ?? 0;
  const rr = v.risk_reward ?? 1;
  return conf * rr;
}

// ── Sub-components ────────────────────────────────────────────

interface GlobalStatusStripProps {
  health: { status: string } | undefined;
  wsStatus: string;
  mode: string;
  executionState: string | undefined;
  openTradeCount: number;
}

function GlobalStatusStrip({
  health,
  wsStatus,
  mode,
  executionState,
  openTradeCount,
}: GlobalStatusStripProps) {
  const backendOk = health?.status === "ok";
  const degraded = mode === "DEGRADED";

  const items = [
    {
      label: "BACKEND",
      value: health ? health.status.toUpperCase() : "UNKNOWN",
      color: health ? statusColor(health.status) : "var(--text-faint)",
      pulse: backendOk,
    },
    {
      label: "LIVE FEED",
      value: wsStatus,
      color: wsStatus === "CONNECTED" ? "var(--green)" : wsStatus === "RECONNECTING" ? "var(--yellow)" : "var(--red)",
      pulse: wsStatus === "CONNECTED",
    },
    {
      label: "ENGINE",
      value: executionState ?? "—",
      color: executionState === "SIGNAL_READY" ? "var(--accent)" : executionState === "EXECUTING" ? "var(--green)" : "var(--text-muted)",
      pulse: false,
    },
    {
      label: "OPEN TRADES",
      value: String(openTradeCount),
      color: openTradeCount > 0 ? "var(--green)" : "var(--text-muted)",
      pulse: false,
    },
    {
      label: "MODE",
      value: degraded ? "DEGRADED" : "NORMAL",
      color: degraded ? "var(--yellow)" : "var(--green)",
      pulse: degraded,
    },
  ];

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 0,
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border-default)",
        overflow: "hidden",
        background: "var(--bg-panel)",
      }}
      role="status"
      aria-label="System status strip"
    >
      {items.map((item, i) => (
        <div
          key={item.label}
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 2,
            padding: "8px 14px",
            borderRight: i < items.length - 1 ? "1px solid var(--border-default)" : "none",
            flex: 1,
            minWidth: 0,
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 8,
              letterSpacing: "0.10em",
              color: "var(--text-faint)",
              fontWeight: 700,
            }}
          >
            {item.label}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {item.pulse && (
              <span
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: item.color,
                  animation: "pulse-dot 1.5s ease-in-out infinite",
                  flexShrink: 0,
                }}
                aria-hidden="true"
              />
            )}
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                fontWeight: 800,
                color: item.color,
                letterSpacing: "0.04em",
              }}
            >
              {item.value}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

interface UrgencyRailProps {
  signals: L12Verdict[];
  accounts: Account[];
  onTake: (v: L12Verdict) => void;
}

function UrgencyRail({ signals, accounts, onTake }: UrgencyRailProps) {
  if (signals.length === 0) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "12px 16px",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--accent)",
        borderLeft: "3px solid var(--accent)",
        background: "rgba(0,229,255,0.04)",
      }}
      role="region"
      aria-label="Actionable signals urgency rail"
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: "var(--accent)",
            animation: "pulse-dot 1s ease-in-out infinite",
            flexShrink: 0,
          }}
          aria-hidden="true"
        />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 800,
            color: "var(--accent)",
            letterSpacing: "0.10em",
          }}
        >
          ACTIONABLE SIGNALS — TOP {signals.length}
        </span>
        <Link
          href="/trades/signals"
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            color: "var(--text-muted)",
            textDecoration: "none",
            padding: "2px 8px",
            border: "1px solid var(--border-default)",
            borderRadius: 3,
          }}
        >
          SIGNAL BOARD →
        </Link>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {signals.map((sig) => (
          <div
            key={sig.symbol}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "7px 10px",
              borderRadius: "var(--radius-sm)",
              background: "rgba(0,0,0,0.2)",
              border: "1px solid var(--border-default)",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                fontWeight: 800,
                color: "var(--text-primary)",
                minWidth: 72,
              }}
            >
              {sig.symbol}
            </span>

            <span
              className={
                String(sig.verdict).includes("BUY")
                  ? "badge badge-cyan"
                  : "badge badge-gold"
              }
              style={{ fontSize: 9 }}
            >
              {sig.verdict}
            </span>

            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--text-muted)",
              }}
            >
              CONF {((sig.confidence ?? 0) * 100).toFixed(0)}%
            </span>

            {sig.risk_reward && (
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--text-secondary)",
                }}
              >
                RR {sig.risk_reward.toFixed(1)}
              </span>
            )}

            {sig.expiry && (
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 9,
                  color: "var(--yellow)",
                  marginLeft: "auto",
                }}
              >
                EXP {sig.expiry}
              </span>
            )}

            <button
              onClick={() => onTake(sig)}
              disabled={accounts.length === 0}
              style={{
                padding: "4px 14px",
                borderRadius: "var(--radius-sm)",
                background: "var(--accent)",
                color: "var(--bg-primary)",
                border: "none",
                fontSize: 10,
                fontWeight: 800,
                letterSpacing: "0.08em",
                cursor: accounts.length === 0 ? "not-allowed" : "pointer",
                fontFamily: "var(--font-mono)",
                opacity: accounts.length === 0 ? 0.4 : 1,
                flexShrink: 0,
              }}
              aria-label={`Take signal for ${sig.symbol}`}
            >
              TAKE
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

interface CriticalRiskStripProps {
  snapshots: AccountRiskSnapshot[];
}

function CriticalRiskStrip({ snapshots }: CriticalRiskStripProps) {
  const breached = snapshots.filter((s) => s.status === "CRITICAL" || s.circuit_breaker);
  const warned = snapshots.filter((s) => s.status === "WARNING" && !s.circuit_breaker);

  if (breached.length === 0 && warned.length === 0) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 16px",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border-danger)",
        borderLeft: "3px solid var(--red)",
        background: "rgba(255,59,48,0.05)",
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
          style={{
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
              background: "var(--red)",
              flexShrink: 0,
              animation: "pulse-dot 1s ease-in-out infinite",
            }}
            aria-hidden="true"
          />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontWeight: 700,
              color: "var(--text-primary)",
            }}
          >
            {s.account_id}
          </span>
          {s.circuit_breaker && (
            <span
              className="badge"
              style={{
                background: "var(--red-glow)",
                color: "var(--red)",
                border: "1px solid var(--border-danger)",
                fontSize: 9,
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
          style={{
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
              flexShrink: 0,
            }}
            aria-hidden="true"
          />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontWeight: 700,
              color: "var(--text-secondary)",
            }}
          >
            {s.account_id}
          </span>
          <span
            className="badge badge-gold"
            style={{ fontSize: 9 }}
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
        padding: "9px 16px",
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
        {blocker.event
          ? `High-impact event: ${blocker.event}`
          : blocker.reason ?? "High-impact event window active — trading signals are blocked."}
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
  return href ? <Link href={href} style={{ textDecoration: "none" }}>{inner}</Link> : inner;
}

// ── Main Page ─────────────────────────────────────────────────

export default function CommandCenterPage() {
  const { data: verdictsRaw, isLoading: vLoading, isError: vError } = useAllVerdicts();
  const { data: activeTradesData, isError: tradesError } = useActiveTrades();
  const { data: context, isError: contextError } = useContext();
  const { data: execution, isError: executionError } = useExecution();
  const { data: accounts, isError: accountsError } = useAccounts();
  const { data: riskSnapshots, isError: riskError } = useAccountsRiskSnapshot();
  const { data: health } = useHealth();
  const { data: calendarBlocker } = useCalendarBlocker();
  const { alerts } = useAlertsWS();

  const wsStatus = useSystemStore((s) => s.wsStatus);
  const mode = useSystemStore((s) => s.mode);

  const [selectedVerdict, setSelectedVerdict] = useState<L12Verdict | null>(null);

  const verdictList = useMemo<L12Verdict[]>(
    () => (Array.isArray(verdictsRaw) ? verdictsRaw : []),
    [verdictsRaw]
  );

  const activeTrades = useMemo<Trade[]>(() => {
    if (!activeTradesData) return [];
    if (Array.isArray(activeTradesData)) return activeTradesData as Trade[];
    const resp = activeTradesData as ActiveTradesResponse;
    return Array.isArray(resp.trades) ? resp.trades : [];
  }, [activeTradesData]);

  const snapshotList = useMemo<AccountRiskSnapshot[]>(
    () => (Array.isArray(riskSnapshots) ? riskSnapshots : []),
    [riskSnapshots]
  );

  // Top 3 actionable signals, ranked by urgency score
  const topActionableSignals = useMemo(
    () =>
      verdictList
        .filter(verdictIsActionable)
        .sort((a, b) => urgencyScore(b) - urgencyScore(a))
        .slice(0, 3),
    [verdictList]
  );

  const executeCount = useMemo(
    () => verdictList.filter((v) => String(v.verdict ?? "").startsWith("EXECUTE")).length,
    [verdictList]
  );

  const highConfidence = useMemo(
    () => verdictList.filter((v) => (v.confidence ?? 0) >= 0.75).length,
    [verdictList]
  );

  const dataErrors = useMemo(() => {
    const errs: string[] = [];
    if (vError)        errs.push("verdicts");
    if (tradesError)   errs.push("trades");
    if (contextError)  errs.push("context");
    if (executionError) errs.push("execution");
    if (accountsError) errs.push("accounts");
    if (riskError)     errs.push("risk");
    return errs;
  }, [vError, tradesError, contextError, executionError, accountsError, riskError]);

  const recentAlerts = useMemo(() => alerts.slice(0, 5), [alerts]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
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
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3, margin: 0 }}>
            What matters now — signals, risk, system state
          </p>
        </div>
      </div>

      {/* 1. Global Status Strip */}
      <GlobalStatusStrip
        health={health}
        wsStatus={wsStatus}
        mode={mode}
        executionState={execution?.state}
        openTradeCount={activeTrades.length}
      />

      {/* 2. Event Banner — high-impact news blackout */}
      <EventBanner blocker={calendarBlocker ?? undefined} />

      {/* 3. Critical Risk Strip */}
      <CriticalRiskStrip snapshots={snapshotList} />

      {/* 4. Data stream diagnostic */}
      {dataErrors.length > 0 && (
        <DataStreamDiagnostic
          failedStreams={dataErrors}
          allStreams={["verdicts", "trades", "context", "execution", "accounts", "risk"]}
        />
      )}

      {/* 5. Urgency Rail — top 3 actionable signals */}
      <UrgencyRail
        signals={topActionableSignals}
        accounts={accounts}
        onTake={setSelectedVerdict}
      />

      {/* 6. KPI bar */}
      <div className="overview-kpi-grid">
        <KpiCard
          label="ACTIONABLE SIGNALS"
          value={executeCount}
          color={executeCount > 0 ? "var(--accent)" : "var(--text-muted)"}
          sub={`of ${verdictList.length} pairs`}
          pulse={executeCount > 0}
          href="/trades/signals"
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
          sub="conf ≥ 75%"
          href="/trades/signals"
        />
        <KpiCard
          label="ENGINE STATE"
          value={execution?.state ?? "—"}
          color={
            execution?.state === "SIGNAL_READY" ? "var(--accent)" :
            execution?.state === "EXECUTING"    ? "var(--green)"  :
            execution?.state === "SCANNING"     ? "var(--blue)"   :
            "var(--text-muted)"
          }
          sub={execution ? `${execution.signal_count ?? 0} signals today` : "no data"}
        />
      </div>

      {/* 7. Main grid: verdicts left, system right */}
      <div className="overview-main-grid">
        {/* Left: all verdict cards */}
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
            <span className="badge badge-gold" style={{ marginLeft: "auto", fontSize: 9 }}>
              {verdictList.length} PAIRS
            </span>
            {context?.session && (
              <span className="badge badge-cyan" style={{ fontSize: 9 }}>
                {context.session}
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
            <div
              className="panel"
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                padding: "32px 20px",
                textAlign: "center",
              }}
            >
              <div style={{ marginBottom: 6, fontSize: 13, color: "var(--text-secondary)" }}>
                No verdicts available
              </div>
              <div style={{ fontSize: 11 }}>
                Connect backend to see live signals.
              </div>
            </div>
          ) : (
            <div className="overview-verdict-grid">
              {verdictList.map((v) => (
                <VerdictCard
                  key={`${v.symbol}-${v.timestamp}`}
                  verdict={v}
                  selected={selectedVerdict?.symbol === v.symbol}
                  onTake={() => setSelectedVerdict(v)}
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
                  { label: "SESSION",    value: context.session },
                  { label: "REGIME",     value: context.regime },
                  { label: "VOLATILITY", value: context.volatility },
                  { label: "TREND",      value: context.trend },
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
              {recentAlerts.map((a, idx) => (
                <div
                  key={idx}
                  style={{
                    fontSize: 11,
                    color: "var(--text-secondary)",
                    borderLeft: "2px solid var(--border-default)",
                    paddingLeft: 8,
                  }}
                >
                  {typeof a === "string" ? a : (a as { message?: string }).message ?? JSON.stringify(a)}
                </div>
              ))}
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
                href="/trades/signals"
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

      {/* ── TakeSignalForm modal ── */}
      {selectedVerdict && accounts.length > 0 && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Take signal form"
          style={{
            position: "fixed",
            inset: 0,
            background: "var(--bg-overlay)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
            backdropFilter: "blur(4px)",
          }}
          onClick={() => setSelectedVerdict(null)}
        >
          <div
            className="animate-fade-in"
            onClick={(e) => e.stopPropagation()}
          >
            <TakeSignalForm
              verdict={selectedVerdict}
              accounts={accounts}
              onDone={() => setSelectedVerdict(null)}
              onCancel={() => setSelectedVerdict(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
