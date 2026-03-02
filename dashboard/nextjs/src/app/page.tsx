"use client";

// ============================================================
// TUYUL FX Wolf-15 — Overview Page (/)
// Data: useAllVerdicts + useHealth + useActiveTrades + useContext
// ============================================================

import { useState } from "react";
import { useAllVerdicts, useHealth, useActiveTrades, useContext, useExecution } from "@/lib/api";
import { VerdictCard } from "@/components/VerdictCard";
import { SystemHealth } from "@/components/SystemHealth";
import { TimezoneDisplay } from "@/components/TimezoneDisplay";
import { TakeSignalForm } from "@/components/TakeSignalForm";
import { useAccounts } from "@/lib/api";
import { useAlertsWS } from "@/lib/websocket";
import { AlertFeed } from "@/components/PropFirmBadge";
import type { L12Verdict } from "@/types";
import { getApiBaseUrl, validateEnv } from "@/lib/env";

export default function Home() {
  // Validate env on every render in dev; no-op in prod if vars are set
  if (typeof window === "undefined") {
    validateEnv(); // server-side only
  }

  const apiBase = getApiBaseUrl();

  const { data: verdicts, isLoading: vLoading } = useAllVerdicts();
  const { data: health } = useHealth();
  const { data: activeTrades } = useActiveTrades();
  const { data: context } = useContext();
  const { data: execution } = useExecution();
  const { data: accounts } = useAccounts();
  const { alerts } = useAlertsWS();

  const [selectedVerdict, setSelectedVerdict] = useState<L12Verdict | null>(null);

  const verdictList = Object.values(verdicts ?? {});
  const executeCount = verdictList.filter((v) =>
    v.verdict.toString().startsWith("EXECUTE")
  ).length;

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 24 }}>
      {/* ── Top bar ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
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
        </div>
        <div style={{ marginLeft: "auto" }}>
          <TimezoneDisplay />
        </div>
      </div>

      {/* ── KPI bar ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
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
          sub={context?.regime ?? ""}
        />
        <KpiCard
          label="ENGINE"
          value={execution?.state ?? "—"}
          color={
            execution?.state === "SIGNAL_READY" ? "var(--accent)" :
            execution?.state === "EXECUTING"    ? "var(--green)" :
            "var(--text-muted)"
          }
          sub={`${execution?.signal_count ?? 0} signals`}
        />
      </div>

      {/* ── Main grid ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 20 }}>
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
            {vLoading && (
              <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                LOADING...
              </span>
            )}
            <span
              className="badge badge-gold"
              style={{ marginLeft: "auto", fontSize: 9 }}
            >
              {verdictList.length} PAIRS
            </span>
          </div>

          {verdictList.length === 0 && !vLoading ? (
            <div
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                padding: "32px 0",
                textAlign: "center",
              }}
            >
              No verdicts available. Waiting for pipeline...
            </div>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: 12,
              }}
            >
              {verdictList.map((v) => (
                <VerdictCard
                  key={v.symbol}
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
      {selectedVerdict && accounts && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
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
      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-muted)", fontWeight: 700 }}>
        {label}
      </div>
      <div className="num" style={{ fontSize: 24, fontWeight: 700, color }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{sub}</div>
      )}
    </div>
  );
}
