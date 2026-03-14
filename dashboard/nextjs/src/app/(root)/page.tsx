"use client";

// ============================================================
// TUYUL FX Wolf-15 — Overview Page (/)
// Production-ready: KPI grid, verdict cards, system sidebar,
//   alert feed, DataStreamDiagnostic, TakeSignalForm modal
// ============================================================

import { useMemo, useState } from "react";
import {
  useAllVerdicts,
  useActiveTrades,
  useContext,
  useExecution,
  useAccounts,
  useHealth,
} from "@/lib/api";
import { VerdictCard } from "@/components/VerdictCard";
import { SystemHealth } from "@/components/SystemHealth";
import { TakeSignalForm } from "@/components/TakeSignalForm";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import DataStreamDiagnostic from "@/components/feedback/DataStreamDiagnostic";
import { useAlertsWS } from "@/lib/websocket";
import { AlertFeed } from "@/components/PropFirmBadge";
import type { L12Verdict } from "@/types";

// ── KPI Card ─────────────────────────────────────────────────

interface KpiCardProps {
  label: string;
  value: string | number;
  color: string;
  sub?: string;
  pulse?: boolean;
}

function KpiCard({ label, value, color, sub, pulse }: KpiCardProps) {
  return (
    <div
      className="card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 5,
        padding: "14px 16px",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Accent line */}
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
          fontSize: 9,
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
}

// ── Main Page ─────────────────────────────────────────────────

export default function Home() {
  const { data: verdictsRaw, isLoading: vLoading, isError: vError } = useAllVerdicts();
  const { data: activeTrades, isError: tradesError } = useActiveTrades();
  const { data: context, isError: contextError } = useContext();
  const { data: execution, isError: executionError } = useExecution();
  const { data: accounts, isError: accountsError } = useAccounts();
  const { data: health } = useHealth();
  const { alerts } = useAlertsWS();

  const [selectedVerdict, setSelectedVerdict] = useState<L12Verdict | null>(null);

  const verdictList = useMemo<L12Verdict[]>(
    () => (Array.isArray(verdictsRaw) ? verdictsRaw : []),
    [verdictsRaw]
  );

  const executeCount = useMemo(
    () => verdictList.filter((v) => String(v.verdict ?? "").startsWith("EXECUTE")).length,
    [verdictList]
  );

  const highConfidence = useMemo(
    () => verdictList.filter((v) => (v.confidence ?? 0) >= 0.75).length,
    [verdictList]
  );

  const activeTradeCount = useMemo(() => {
    if (!activeTrades) return 0;
    if (Array.isArray(activeTrades)) return activeTrades.length;
    return Array.isArray((activeTrades as { trades?: unknown[] }).trades)
      ? (activeTrades as { trades: unknown[] }).trades.length
      : 0;
  }, [activeTrades]);

  const dataErrors = useMemo(() => {
    const errs: string[] = [];
    if (vError)        errs.push("verdicts");
    if (tradesError)   errs.push("trades");
    if (contextError)  errs.push("context");
    if (executionError)errs.push("execution");
    if (accountsError) errs.push("accounts");
    return errs;
  }, [vError, tradesError, contextError, executionError, accountsError]);

  const hasDataError = dataErrors.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="dashboard" />

      {/* ── Page title ── */}
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
            WOLF-15 OVERVIEW
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            Institutional-grade multi-layer pipeline analysis
          </p>
        </div>
        {/* Backend indicator */}
        {health && (
          <div
            style={{
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              borderRadius: "var(--radius-sm)",
              background: health.status === "ok" ? "var(--green-glow)" : "var(--red-glow)",
              border: `1px solid ${health.status === "ok" ? "var(--border-success)" : "var(--border-danger)"}`,
            }}
          >
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: health.status === "ok" ? "var(--green)" : "var(--red)",
                display: "inline-block",
                animation: health.status === "ok" ? "pulse-dot 1.5s ease-in-out infinite" : "none",
              }}
            />
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 700, color: health.status === "ok" ? "var(--green)" : "var(--red)" }}>
              {health.status.toUpperCase()}
            </span>
          </div>
        )}
      </div>

      {/* ── Data stream diagnostic ── */}
      {hasDataError && (
        <DataStreamDiagnostic
          failedStreams={dataErrors}
          allStreams={["verdicts", "trades", "context", "execution", "accounts"]}
        />
      )}

      {/* ── KPI bar ── */}
      <div className="overview-kpi-grid">
        <KpiCard
          label="ACTIVE SIGNALS"
          value={executeCount}
          color={executeCount > 0 ? "var(--accent)" : "var(--text-muted)"}
          sub={`of ${verdictList.length} pairs scanned`}
          pulse={executeCount > 0}
        />
        <KpiCard
          label="OPEN TRADES"
          value={activeTradeCount}
          color={activeTradeCount > 0 ? "var(--green)" : "var(--text-muted)"}
          sub="live positions"
        />
        <KpiCard
          label="HIGH CONFIDENCE"
          value={highConfidence}
          color={highConfidence > 0 ? "var(--cyan)" : "var(--text-muted)"}
          sub="conf >= 75%"
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
          sub={execution ? `${execution.signal_count} signals today` : undefined}
        />
      </div>

      {/* ── Main content grid ── */}
      <div className="overview-main-grid">
        {/* ── Left: Verdict cards ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Section header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.12em",
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            L12 VERDICTS
            {vLoading && (
              <span style={{ fontSize: 9, color: "var(--text-faint)", fontWeight: 400 }}>
                LOADING...
              </span>
            )}
            <span
              className="badge badge-gold"
              style={{ marginLeft: "auto", fontSize: 9 }}
            >
              {verdictList.length} PAIRS
            </span>
            {context?.session && (
              <span className="badge badge-cyan" style={{ fontSize: 9 }}>
                {context.session}
              </span>
            )}
          </div>

          {/* Skeleton loading */}
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
              <div style={{ marginBottom: 6, fontSize: 14, color: "var(--text-secondary)" }}>
                No verdicts available
              </div>
              <div style={{ fontSize: 11 }}>
                Waiting for pipeline warmup / Redis candles.
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

        {/* ── Right sidebar: system + alerts ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SystemHealth />

          {/* Context snapshot */}
          {context && (
            <div className="panel" style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                MARKET CONTEXT
              </div>
              {[
                { label: "SESSION",    value: context.session },
                { label: "REGIME",     value: context.regime },
                { label: "VOLATILITY", value: context.volatility },
                { label: "TREND",      value: context.trend },
              ].map(({ label, value }) => value && (
                <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                  <span style={{ color: "var(--text-muted)" }}>{label}</span>
                  <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)", fontWeight: 700 }}>
                    {value}
                  </span>
                </div>
              ))}
            </div>
          )}

          <AlertFeed alerts={alerts} maxVisible={12} />
        </div>
      </div>

      {/* ── TakeSignalForm modal ── */}
      {selectedVerdict && accounts && accounts.length > 0 && (
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
