"use client";

// ============================================================
// TUYUL FX Wolf-15 — Overview Page (/)
// Data: useAllVerdicts + useHealth + useActiveTrades + useContext
// ============================================================

import { useMemo, useState } from "react";
import {
  useAllVerdicts,
  useActiveTrades,
  useContext,
  useExecution,
  useAccounts,
} from "@/lib/api";
import { VerdictCard } from "@/components/VerdictCard";
import { SystemHealth } from "@/components/SystemHealth";
import { TimezoneDisplay } from "@/components/TimezoneDisplay";
import { TakeSignalForm } from "@/components/TakeSignalForm";
import { useAlertsWS } from "@/lib/websocket";
import { AlertFeed } from "@/components/PropFirmBadge";
import type { L12Verdict } from "@/types";
import { getApiBaseUrl } from "@/lib/env";

export default function Home() {
  const apiBase = getApiBaseUrl();

  const { data: verdictsRaw, isLoading: vLoading, isError: vError } = useAllVerdicts();
  const { data: activeTrades, isError: tradesError } = useActiveTrades();
  const { data: context, isError: contextError } = useContext();
  const { data: execution, isError: executionError } = useExecution();
  const { data: accounts, isError: accountsError } = useAccounts();
  const { alerts } = useAlertsWS();

  const [selectedVerdict, setSelectedVerdict] = useState<L12Verdict | null>(null);

  const verdictList = useMemo<L12Verdict[]>(
    () => (Array.isArray(verdictsRaw) ? verdictsRaw : []),
    [verdictsRaw],
  );

  const executeCount = useMemo(
    () =>
      verdictList.filter((v) => String(v.verdict ?? "").startsWith("EXECUTE")).length,
    [verdictList],
  );

  const hasDataError = vError || tradesError || contextError || executionError || accountsError;

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* ── Top bar ── */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 700,
              letterSpacing: "0.04em",
              color: "var(--text-primary)",
              margin: 0,
            }}
          >
            WOLF-15 OVERVIEW
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Institutional-grade pipeline analysis
          </p>
          <p style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 6 }}>
            API: <span className="num">{apiBase || "NOT_SET"}</span>
          </p>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <TimezoneDisplay />
        </div>
      </div>

      {/* ── Data error banner ── */}
      {hasDataError && (
        <div
          className="panel"
          style={{
            borderColor: "rgba(255, 77, 79, 0.35)",
            background: "rgba(255, 77, 79, 0.08)",
            padding: 12,
            fontSize: 12,
            color: "var(--text-primary)",
          }}
        >
          Data stream issue detected. Periksa NEXT_PUBLIC_API_URL / NEXT_PUBLIC_API_BASE_URL,
          endpoint Railway, dan CORS backend.
        </div>
      )}

      {/* ── KPI bar ── */}
      <div className="overview-kpi-grid">
        <KpiCard
          label="ACTIVE SIGNALS"
          value={executeCount}
          color={executeCount > 0 ? "var(--accent)" : "var(--text-muted)"}
          sub={`of ${verdictList.length} pairs`}
        />
        <KpiCard
          label="OPEN TRADES"
          value={activeTrades?.length ?? 0}
          color={activeTrades?.length ? "var(--green)" : "var(--text-muted)"}
          sub="live positions"
        />
        <KpiCard
          label="SESSION"
          value={context?.session ?? "—"}
          color="var(--blue)"
          sub={context?.regime ?? "NO REGIME"}
        />
        <KpiCard
          label="ENGINE"
          value={execution?.state ?? "—"}
          color={
            execution?.state === "SIGNAL_READY"
              ? "var(--accent)"
              : execution?.state === "EXECUTING"
                ? "var(--green)"
                : "var(--text-muted)"
          }
          sub={`${execution?.signal_count ?? 0} signals`}
        />
      </div>

      {/* ── Main grid ── */}
      <div className="overview-main-grid">
        {/* ── Verdict grid ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.1em",
              color: "var(--text-muted)",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            L12 VERDICTS
            {vLoading && <span style={{ fontSize: 10, color: "var(--text-muted)" }}>LOADING...</span>}
            <span className="badge badge-gold" style={{ marginLeft: "auto", fontSize: 9 }}>
              {verdictList.length} PAIRS
            </span>
          </div>

          {vLoading ? (
            <div className="overview-verdict-grid">
              {Array.from({ length: 6 }).map((_, idx) => (
                <div
                  key={`skeleton-${idx}`}
                  className="card"
                  style={{
                    minHeight: 160,
                    opacity: 0.65,
                    background:
                      "linear-gradient(110deg, rgba(255,255,255,0.04) 8%, rgba(255,255,255,0.08) 18%, rgba(255,255,255,0.04) 33%)",
                    backgroundSize: "200% 100%",
                    animation: "skeleton-loading 1.4s linear infinite",
                  }}
                />
              ))}
            </div>
          ) : verdictList.length === 0 ? (
            <div
              className="panel"
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                padding: "28px 16px",
                textAlign: "center",
              }}
            >
              No verdicts available. Waiting for pipeline warmup / Redis candles.
            </div>
          ) : (
            <div className="overview-verdict-grid">
              {verdictList.map((v) => (
                <VerdictCard
                  key={`${v.symbol}-${v.timestamp}`}
                  verdict={v}
                  selected={selectedVerdict?.symbol === v.symbol}
                  onTake={() => setSelectedVerdict(v)}
                  onSkip={() => setSelectedVerdict(v)}
                />
              ))}
            </div>
          )}
        </div>

        {/* ── Right sidebar ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SystemHealth />
          <AlertFeed alerts={alerts} maxVisible={10} />
        </div>
      </div>

      {/* ── TakeSignalForm overlay ── */}
      {selectedVerdict && accounts && accounts.length > 0 && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
          }}
          onClick={() => setSelectedVerdict(null)}
        >
          <div onClick={(e) => e.stopPropagation()}>
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

function KpiCard({
  label,
  value,
  color,
  sub,
}: {
  label: string;
  value: string | number;
  color: string;
  sub?: string;
}) {
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div
        style={{
          fontSize: 9,
          letterSpacing: "0.1em",
          color: "var(--text-muted)",
          fontWeight: 700,
        }}
      >
        {label}
      </div>
      <div className="num" style={{ fontSize: 24, fontWeight: 700, color }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{sub}</div>}
    </div>
  );
}
