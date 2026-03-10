"use client";

// ============================================================
// TUYUL FX Wolf-15 — Risk Monitor Page (/risk)
// Data: useRiskSnapshot + WS /ws/risk + /ws/equity
// ============================================================

import { useState } from "react";
import { useAccounts, useRiskSnapshot } from "@/lib/api";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { RiskGauge } from "@/components/RiskGauge";
import { EquityCurve } from "@/components/EquityCurve";
import { useRiskWS } from "@/lib/websocket";
import type { Account } from "@/types";

export default function RiskPage() {
  const { data: accounts, isLoading } = useAccounts();
  const [selectedAccountId, setSelectedAccountId] = useState<string>("");

  const activeAccountId =
    selectedAccountId || accounts?.[0]?.account_id || "";

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="risk" />

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
            RISK MONITOR
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Drawdown tracking + circuit breaker status
          </p>
        </div>

        {/* Account selector */}
        {accounts && accounts.length > 1 && (
          <select
            value={activeAccountId}
            onChange={(e) => setSelectedAccountId(e.target.value)}
            style={{ marginLeft: "auto", fontSize: 12 }}
          >
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.account_name}
              </option>
            ))}
          </select>
        )}
      </div>

      {isLoading ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
          Loading accounts...
        </div>
      ) : (accounts ?? []).length === 0 ? (
        <div
          style={{
            fontSize: 12,
            color: "var(--text-muted)",
            padding: 24,
            textAlign: "center",
          }}
        >
          No accounts found. Add an account first.
        </div>
      ) : (
        <RiskContent accountId={activeAccountId} />
      )}
    </div>
  );
}

function RiskContent({ accountId }: { accountId: string }) {
  const { data: snapshot } = useRiskSnapshot(accountId);
  const { data: wsSnapshot, connected } = useRiskWS(accountId);

  // Prefer WS data, fall back to REST
  const live = wsSnapshot ?? snapshot;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "380px 1fr", gap: 20, alignItems: "start" }}>
      {/* ── Left: Gauges ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {/* WS indicator */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: connected ? "var(--green)" : "var(--yellow)",
              display: "inline-block",
            }}
          />
          {connected ? "REAL-TIME (WS)" : "POLLING (REST)"}
        </div>

        {live ? (
          <RiskGauge snapshot={live} />
        ) : (
          <div
            style={{
              padding: 24,
              fontSize: 12,
              color: "var(--text-muted)",
              background: "var(--bg-panel)",
              borderRadius: 8,
              textAlign: "center",
            }}
          >
            Loading risk snapshot...
          </div>
        )}

        {/* Risk rules card */}
        <div className="card">
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.1em",
              color: "var(--text-muted)",
              marginBottom: 12,
            }}
          >
            DD MULTIPLIER RULES
          </div>
          <table>
            <thead>
              <tr>
                <th>DD LEVEL</th>
                <th>MULTIPLIER</th>
                <th>EFFECT</th>
              </tr>
            </thead>
            <tbody>
              {[
                { range: "< 30%",   mult: "1.00×", effect: "Full risk" },
                { range: "30–60%",  mult: "0.75×", effect: "Reduced" },
                { range: "60–80%",  mult: "0.50×", effect: "Half size" },
                { range: "> 80%",   mult: "0.25×", effect: "Emergency" },
              ].map(({ range, mult, effect }) => (
                <tr key={range}>
                  <td className="num">{range}</td>
                  <td className="num" style={{ color: "var(--accent)" }}>{mult}</td>
                  <td style={{ color: "var(--text-muted)" }}>{effect}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Right: Equity curve ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <EquityCurve accountId={accountId} height={200} />

        {/* Prop firm guard history */}
        {live && (
          <div className="card">
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.1em",
                color: "var(--text-muted)",
                marginBottom: 12,
              }}
            >
              ACCOUNT RISK STATE
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2, 1fr)",
                gap: 12,
              }}
            >
              {[
                { label: "DAILY DD",       value: `${live.daily_dd_percent?.toFixed(2)}%` },
                { label: "DAILY LIMIT",    value: `${live.daily_dd_limit?.toFixed(1)}%` },
                { label: "TOTAL DD",       value: `${live.total_dd_percent?.toFixed(2)}%` },
                { label: "OPEN TRADES",    value: live.open_trades },
                { label: "OPEN RISK",      value: `${live.open_risk_percent?.toFixed(2)}%` },
                { label: "CIRCUIT BREAKER",value: live.circuit_breaker },
              ].map(({ label, value }) => (
                <div key={label}>
                  <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em", marginBottom: 2 }}>
                    {label}
                  </div>
                  <div className="num" style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>
                    {value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
