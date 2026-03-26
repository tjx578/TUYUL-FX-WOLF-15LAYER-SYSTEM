"use client";

import { useRiskSnapshot } from "../api/risk.api";
import { useLiveRisk } from "../hooks/useLiveRisk";
import { DD_MULTIPLIER_RULES } from "../model/risk.types";
import { RiskGauge } from "./RiskGauge";
import { EquityCurve } from "./EquityCurve";
import { RiskStat } from "./RiskStat";

export function RiskContent({ accountId }: { accountId: string }) {
  const { data: snapshot } = useRiskSnapshot(accountId);
  const { snapshot: wsSnapshot, status } = useLiveRisk(snapshot ?? null, accountId);
  const connected = status === "LIVE";
  const live = wsSnapshot ?? snapshot;

  const cbColor = live?.circuit_breaker === "OPEN"
    ? "var(--red)"
    : live?.circuit_breaker === "HALF_OPEN"
      ? "var(--yellow)"
      : "var(--green)";

  return (
    <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: 20, alignItems: "start" }}>
      {/* Left: Gauges */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {/* Live indicator */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: connected ? "var(--green)" : "var(--yellow)",
              display: "inline-block",
              animation: connected ? "pulse-dot 1.5s ease-in-out infinite" : "none",
            }}
          />
          {connected ? "REAL-TIME (WEBSOCKET)" : "POLLING (REST)"}
        </div>

        {live ? (
          <RiskGauge snapshot={live} />
        ) : (
          <div className="skeleton card" style={{ height: 180 }} aria-label="Loading risk gauge" />
        )}

        {/* DD Multiplier rules */}
        <div className="card">
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: 12, fontFamily: "var(--font-mono)" }}>
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
              {DD_MULTIPLIER_RULES.map(({ range, mult, effect, color }) => (
                <tr key={range}>
                  <td className="num">{range}</td>
                  <td className="num" style={{ color: "var(--accent)", fontWeight: 700 }}>{mult}</td>
                  <td style={{ color }}>{effect}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Right: Equity + State */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <EquityCurve accountId={accountId} height={210} />

        {live && (
          <div className="card">
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: 14, fontFamily: "var(--font-mono)" }}>
              LIVE RISK STATE
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
              <RiskStat
                label="DAILY DD"
                value={`${live.daily_dd_percent?.toFixed(2)}%`}
                color={live.daily_dd_percent > live.daily_dd_limit * 0.7 ? "var(--red)" : "var(--green)"}
              />
              <RiskStat
                label="DAILY LIMIT"
                value={`${live.daily_dd_limit?.toFixed(1)}%`}
              />
              <RiskStat
                label="TOTAL DD"
                value={`${live.total_dd_percent?.toFixed(2)}%`}
                color={live.total_dd_percent > 5 ? "var(--red)" : "var(--text-primary)"}
              />
              <RiskStat
                label="OPEN RISK"
                value={`${live.open_risk_percent?.toFixed(2)}%`}
              />
              <RiskStat
                label="OPEN TRADES"
                value={String(live.open_trades)}
                color="var(--blue)"
              />
              <RiskStat
                label="CIRCUIT BREAKER"
                value={String(live.circuit_breaker)}
                color={cbColor}
              />
            </div>

            {/* Can-trade indicator */}
            <div
              style={{
                marginTop: 14,
                padding: "10px 12px",
                borderRadius: "var(--radius-sm)",
                background: live.can_trade ? "var(--green-glow)" : "var(--red-glow)",
                border: `1px solid ${live.can_trade ? "var(--border-success)" : "var(--border-danger)"}`,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: live.can_trade ? "var(--green)" : "var(--red)",
                  display: "inline-block",
                  animation: live.can_trade ? "pulse-dot 1.5s ease-in-out infinite" : "none",
                  flexShrink: 0,
                }}
              />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, color: live.can_trade ? "var(--green)" : "var(--red)" }}>
                {live.can_trade ? "TRADING ALLOWED" : "TRADING BLOCKED"}
              </span>
              {live.block_reason && (
                <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 4 }}>
                  — {live.block_reason}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
