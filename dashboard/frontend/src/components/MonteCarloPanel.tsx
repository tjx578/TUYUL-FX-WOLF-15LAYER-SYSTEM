"use client";

/**
 * MonteCarloPanel — L7 Monte Carlo + Bayesian Probability Display
 *
 * Shows:
 * - MC simulation results (win rate, profit factor, risk of ruin)
 * - Bayesian posterior + confidence interval
 * - Win rate distribution histogram
 * - Calibration metrics from L13 reflection
 *
 * Props:
 *   data: MCProbabilityData (from /api/v1/dashboard/signals/{id}/probability)
 */

import React, { useMemo } from "react";

// ── Types ───────────────────────────────────────────────────────

export interface MCProbabilityData {
  monteCarloWinRate: number;
  profitFactor: number;
  riskOfRuin: number;
  expectedValue: number;
  maxDrawdown: number;
  simulations: number;
  bayesianPosterior: number;
  bayesianCI: [number, number];
  calibrationError: number;
  calibrationGrade: string;
  mcPassed: boolean;
  l7Validation: "PASS" | "FAIL" | "WARN";
}

interface MonteCarloPanelProps {
  data: MCProbabilityData;
  showHistogram?: boolean;
}

// ── Constants ───────────────────────────────────────────────────

const GREEN = "#10b981";
const RED = "#ef4444";
const GOLD = "#d4af37";
const BLUE = "#3b82f6";
const PURPLE = "#a855f7";
const AMBER = "#f59e0b";

// ── Component ───────────────────────────────────────────────────

export function MonteCarloPanel({
  data,
  showHistogram = true,
}: MonteCarloPanelProps): React.ReactElement {
  const validationColor =
    data.l7Validation === "PASS"
      ? GREEN
      : data.l7Validation === "WARN"
        ? AMBER
        : RED;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* L7 Validation badge */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: validationColor,
              boxShadow: `0 0 6px ${validationColor}66`,
            }}
          />
          <span
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: validationColor,
            }}
          >
            L7: {data.l7Validation}
          </span>
        </div>
        <span style={{ fontSize: 10, color: "#555" }}>
          {data.simulations.toLocaleString()} simulations
        </span>
      </div>

      {/* Key metrics grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 10,
        }}
      >
        <MetricBox
          label="MC Win Rate"
          value={`${data.monteCarloWinRate.toFixed(1)}%`}
          color={data.monteCarloWinRate >= 55 ? GREEN : RED}
          sub="target: ≥55%"
        />
        <MetricBox
          label="Profit Factor"
          value={data.profitFactor.toFixed(2)}
          color={data.profitFactor >= 1.5 ? GOLD : AMBER}
          sub="target: ≥1.50"
        />
        <MetricBox
          label="Risk of Ruin"
          value={`${data.riskOfRuin.toFixed(1)}%`}
          color={data.riskOfRuin < 5 ? GREEN : RED}
          sub="target: <5%"
        />
        <MetricBox
          label="Expected Value"
          value={`$${data.expectedValue.toFixed(2)}`}
          color={data.expectedValue > 0 ? BLUE : RED}
          sub="per trade avg"
        />
        <MetricBox
          label="Max Drawdown"
          value={`${data.maxDrawdown.toFixed(1)}%`}
          color={data.maxDrawdown < 10 ? AMBER : RED}
          sub="MC worst case"
        />
        <MetricBox
          label="MC Gate"
          value={data.mcPassed ? "PASS" : "FAIL"}
          color={data.mcPassed ? GREEN : RED}
          sub="confidence gate"
        />
      </div>

      {/* Bayesian section */}
      <div
        style={{
          background: "#0a0a0a",
          border: "1px solid #1a1a1a",
          borderRadius: 10,
          padding: 16,
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: PURPLE,
            marginBottom: 12,
            letterSpacing: 0.5,
          }}
        >
          BAYESIAN CALIBRATION
        </div>

        {/* Posterior bar with CI */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginBottom: 6,
          }}
        >
          <span style={{ fontSize: 11, color: "#666" }}>
            Posterior Probability
          </span>
          <span
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: PURPLE,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {(data.bayesianPosterior * 100).toFixed(1)}%
          </span>
        </div>

        {/* CI visualization */}
        <div
          style={{
            height: 8,
            background: "#111",
            borderRadius: 4,
            overflow: "hidden",
            position: "relative",
          }}
        >
          {/* CI range */}
          <div
            style={{
              position: "absolute",
              left: `${data.bayesianCI[0] * 100}%`,
              right: `${(1 - data.bayesianCI[1]) * 100}%`,
              height: "100%",
              background: `${PURPLE}30`,
              borderRadius: 4,
            }}
          />
          {/* Posterior point */}
          <div
            style={{
              position: "absolute",
              left: `${data.bayesianPosterior * 100}%`,
              top: -1,
              width: 3,
              height: 10,
              background: PURPLE,
              borderRadius: 2,
              transform: "translateX(-50%)",
            }}
          />
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 9,
            color: "#555",
            marginTop: 4,
          }}
        >
          <span>
            CI Low: {(data.bayesianCI[0] * 100).toFixed(0)}%
          </span>
          <span>
            CI High: {(data.bayesianCI[1] * 100).toFixed(0)}%
          </span>
        </div>

        {/* Calibration metrics */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 8,
            marginTop: 12,
          }}
        >
          <div
            style={{
              background: "#111",
              borderRadius: 6,
              padding: "8px 10px",
            }}
          >
            <div style={{ fontSize: 9, color: "#555" }}>
              Calibration Error
            </div>
            <div
              style={{
                fontSize: 14,
                fontWeight: 700,
                color:
                  data.calibrationError < 0.05 ? GREEN : AMBER,
              }}
            >
              {(data.calibrationError * 100).toFixed(1)}%
            </div>
          </div>
          <div
            style={{
              background: "#111",
              borderRadius: 6,
              padding: "8px 10px",
            }}
          >
            <div style={{ fontSize: 9, color: "#555" }}>
              Calibration Grade
            </div>
            <div
              style={{
                fontSize: 14,
                fontWeight: 700,
                color: GREEN,
              }}
            >
              {data.calibrationGrade}
            </div>
          </div>
        </div>
      </div>

      {/* Histogram */}
      {showHistogram && (
        <div
          style={{
            background: "#0a0a0a",
            border: "1px solid #1a1a1a",
            borderRadius: 10,
            padding: 16,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "#888",
              marginBottom: 12,
            }}
          >
            WIN RATE DISTRIBUTION
          </div>
          <MCHistogram
            winRate={data.monteCarloWinRate}
            threshold={55}
          />
        </div>
      )}
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────

function MetricBox({
  label,
  value,
  color,
  sub,
}: {
  label: string;
  value: string;
  color: string;
  sub: string;
}) {
  return (
    <div
      style={{
        background: "#0a0a0a",
        border: "1px solid #1a1a1a",
        borderRadius: 8,
        padding: "10px 12px",
      }}
    >
      <div style={{ fontSize: 9, color: "#555", marginBottom: 4 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 700,
          color,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 9, color: "#444", marginTop: 2 }}>
        {sub}
      </div>
    </div>
  );
}

function MCHistogram({
  winRate,
  threshold,
}: {
  winRate: number;
  threshold: number;
}) {
  const bins = useMemo(() => {
    return Array.from({ length: 20 }, (_, i) => {
      const center = 30 + i * 2.5;
      const dist = Math.abs(center - winRate);
      const height = Math.max(3, 100 * Math.exp((-dist * dist) / 120));
      return { center, height, aboveThreshold: center >= threshold };
    });
  }, [winRate, threshold]);

  const maxH = Math.max(...bins.map((b) => b.height));

  return (
    <div
      style={{
        display: "flex",
        alignItems: "end",
        gap: 2,
        height: 100,
      }}
    >
      {bins.map((bin, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
          }}
        >
          <div
            style={{
              width: "100%",
              borderRadius: "2px 2px 0 0",
              height: `${(bin.height / maxH) * 80}px`,
              background: bin.aboveThreshold
                ? `${GREEN}80`
                : `${RED}40`,
              transition: "height 0.5s ease",
            }}
          />
          {i % 4 === 0 && (
            <span
              style={{
                fontSize: 8,
                color: "#444",
                marginTop: 3,
              }}
            >
              {bin.center.toFixed(0)}%
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export default MonteCarloPanel;
