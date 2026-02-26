"use client";

// ============================================================
// TUYUL FX Wolf-15 — Risk Gauge Component
// Used by: /risk page
// ============================================================

import type { RiskSnapshot } from "@/types";
import { CircuitBreakerState } from "@/types";
import { motion } from "framer-motion";

interface RiskGaugeProps {
  snapshot: RiskSnapshot;
}

function GaugeBar({
  label,
  value,
  limit,
  color,
}: {
  label: string;
  value: number;
  limit: number;
  color: string;
}) {
  const pct = limit > 0 ? Math.min((value / limit) * 100, 100) : 0;
  const severity =
    pct >= 80 ? "var(--red)" : pct >= 50 ? "var(--yellow)" : color;

  return (
    <div style={{ marginBottom: 14 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "var(--text-muted)",
          marginBottom: 4,
          letterSpacing: "0.06em",
        }}
      >
        <span>{label}</span>
        <span className="num" style={{ color: severity }}>
          {value.toFixed(2)}% / {limit.toFixed(1)}%
        </span>
      </div>
      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{
            width: `${pct}%`,
            background: severity,
            transition: "width 0.4s ease, background 0.4s ease",
          }}
        />
      </div>
    </div>
  );
}

export function RiskGauge({ snapshot }: RiskGaugeProps) {
  const cbColor =
    snapshot.circuit_breaker === CircuitBreakerState.OPEN
      ? "var(--red)"
      : snapshot.circuit_breaker === CircuitBreakerState.HALF_OPEN
      ? "var(--yellow)"
      : "var(--green)";

  // Breathing pulse: triggers when daily OR total DD exceeds 85% of limit
  const dailyPct  = snapshot.daily_dd_limit  > 0 ? (snapshot.daily_dd_percent  / snapshot.daily_dd_limit)  * 100 : 0;
  const totalPct  = snapshot.total_dd_limit  > 0 ? (snapshot.total_dd_percent  / snapshot.total_dd_limit)  * 100 : 0;
  const pulseCritical = dailyPct > 85 || totalPct > 85;

  return (
    <motion.div
      className="card"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
      animate={{ scale: pulseCritical ? [1, 1.025, 1] : 1 }}
      transition={{
        repeat: pulseCritical ? Infinity : 0,
        duration: 1.5,
        ease: "easeInOut",
      }}
    >
      {/* Section header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.1em",
            color: "var(--text-muted)",
          }}
        >
          RISK SNAPSHOT
        </div>
        <span
          className="badge"
          style={{
            fontSize: 9,
            background: `${cbColor}1a`,
            color: cbColor,
            borderColor: `${cbColor}40`,
          }}
        >
          CB: {snapshot.circuit_breaker}
        </span>
      </div>

      {/* Gauges */}
      <GaugeBar
        label="DAILY DRAWDOWN"
        value={snapshot.daily_dd_percent}
        limit={snapshot.daily_dd_limit}
        color="var(--accent)"
      />
      <GaugeBar
        label="TOTAL DRAWDOWN"
        value={snapshot.total_dd_percent}
        limit={snapshot.total_dd_limit}
        color="var(--blue)"
      />

      {/* Summary row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 10,
          paddingTop: 10,
          borderTop: "1px solid var(--bg-border)",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 9,
              color: "var(--text-muted)",
              letterSpacing: "0.08em",
              marginBottom: 2,
            }}
          >
            OPEN TRADES
          </div>
          <div
            className="num"
            style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}
          >
            {snapshot.open_trades}
          </div>
        </div>
        <div>
          <div
            style={{
              fontSize: 9,
              color: "var(--text-muted)",
              letterSpacing: "0.08em",
              marginBottom: 2,
            }}
          >
            OPEN RISK
          </div>
          <div
            className="num"
            style={{ fontSize: 16, fontWeight: 700, color: "var(--accent)" }}
          >
            {snapshot.open_risk_percent?.toFixed(2)}%
          </div>
        </div>
        <div>
          <div
            style={{
              fontSize: 9,
              color: "var(--text-muted)",
              letterSpacing: "0.08em",
              marginBottom: 2,
            }}
          >
            SEVERITY
          </div>
          <div
            className="num"
            style={{
              fontSize: 14,
              fontWeight: 700,
              color:
                snapshot.severity === "CRITICAL"
                  ? "var(--red)"
                  : snapshot.severity === "WARNING"
                  ? "var(--yellow)"
                  : "var(--green)",
            }}
          >
            {snapshot.severity}
          </div>
        </div>
      </div>
    </div>
  );
}
