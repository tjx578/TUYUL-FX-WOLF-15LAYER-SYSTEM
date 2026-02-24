"use client";

/**
 * DrawdownMeter — Real-time Drawdown Monitoring Component
 *
 * Standalone component showing:
 * - Daily/Weekly/Total drawdown vs prop firm limits
 * - Visual progress bars with warning zones (80% threshold)
 * - Circuit breaker status
 * - DD-based risk multiplier display
 * - Color escalation: green → amber → red
 *
 * Props:
 *   drawdown: DrawdownData (from account state API)
 *   limits: DrawdownLimits (from prop firm profile)
 */

import React, { useMemo } from "react";

// ── Types ───────────────────────────────────────────────────────

export interface DrawdownData {
  dailyPercent: number;
  weeklyPercent: number;
  totalPercent: number;
  equityHigh: number;
  currentEquity: number;
}

export interface DrawdownLimits {
  dailyMax: number;
  weeklyMax: number;
  totalMax: number;
}

interface DrawdownMeterProps {
  drawdown: DrawdownData;
  limits: DrawdownLimits;
  showMultiplier?: boolean;
  showCircuitBreaker?: boolean;
}

// ── Constants ───────────────────────────────────────────────────

const GREEN = "#10b981";
const AMBER = "#f59e0b";
const RED = "#ef4444";

const DD_MULTIPLIER_STEPS = [
  { maxDD: 2, multiplier: 1.0, label: "<2%", color: GREEN },
  { maxDD: 4, multiplier: 0.8, label: "2-4%", color: AMBER },
  { maxDD: 6, multiplier: 0.5, label: "4-6%", color: AMBER },
  { maxDD: 8, multiplier: 0.25, label: "6-8%", color: RED },
  { maxDD: Infinity, multiplier: 0, label: ">8%", color: RED },
];

function getColor(pct: number): string {
  if (pct > 80) return RED;
  if (pct > 50) return AMBER;
  return GREEN;
}

function getMultiplier(totalDD: number): {
  multiplier: number;
  label: string;
  color: string;
} {
  for (const step of DD_MULTIPLIER_STEPS) {
    if (totalDD < step.maxDD) {
      return {
        multiplier: step.multiplier,
        label: step.label,
        color: step.color,
      };
    }
  }
  return { multiplier: 0, label: "STOP", color: RED };
}

// ── Component ───────────────────────────────────────────────────

export function DrawdownMeter({
  drawdown,
  limits,
  showMultiplier = true,
  showCircuitBreaker = true,
}: DrawdownMeterProps): React.ReactElement {
  const meters = useMemo(
    () => [
      {
        label: "Daily",
        current: drawdown.dailyPercent,
        limit: limits.dailyMax,
      },
      {
        label: "Weekly",
        current: drawdown.weeklyPercent,
        limit: limits.weeklyMax,
      },
      {
        label: "Total",
        current: drawdown.totalPercent,
        limit: limits.totalMax,
      },
    ],
    [drawdown, limits]
  );

  const isBreaker =
    drawdown.dailyPercent >= limits.dailyMax ||
    drawdown.totalPercent >= limits.totalMax;
  const multiplierInfo = getMultiplier(drawdown.totalPercent);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Circuit breaker status */}
      {showCircuitBreaker && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "10px 14px",
            borderRadius: 8,
            background: isBreaker ? `${RED}0a` : `${GREEN}0a`,
            border: `1px solid ${isBreaker ? RED : GREEN}22`,
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
                background: isBreaker ? RED : GREEN,
                boxShadow: `0 0 6px ${isBreaker ? RED : GREEN}66`,
              }}
            />
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: isBreaker ? RED : GREEN,
              }}
            >
              Circuit Breaker: {isBreaker ? "TRIPPED" : "CLOSED"}
            </span>
          </div>
          <span
            style={{
              fontSize: 10,
              color: "#555",
            }}
          >
            Equity: $
            {drawdown.currentEquity.toLocaleString(undefined, {
              minimumFractionDigits: 2,
            })}
          </span>
        </div>
      )}

      {/* Drawdown bars */}
      {meters.map((meter) => {
        const pct = (meter.current / meter.limit) * 100;
        const color = getColor(pct);
        const remaining = meter.limit - meter.current;

        return (
          <div key={meter.label}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: 5,
              }}
            >
              <span style={{ fontSize: 11, color: "#888" }}>
                {meter.label} Drawdown
              </span>
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {meter.current.toFixed(2)}% / {meter.limit.toFixed(1)}%
              </span>
            </div>
            <div
              style={{
                height: 10,
                background: "#111",
                borderRadius: 5,
                overflow: "hidden",
                position: "relative",
              }}
            >
              {/* Progress */}
              <div
                style={{
                  height: "100%",
                  borderRadius: 5,
                  background: color,
                  width: `${Math.min(pct, 100)}%`,
                  transition: "width 0.8s ease",
                }}
              />
              {/* 80% warning line */}
              <div
                style={{
                  position: "absolute",
                  left: "80%",
                  top: 0,
                  width: 1,
                  height: "100%",
                  background: `${RED}40`,
                }}
              />
            </div>
            <div
              style={{
                fontSize: 10,
                color: "#444",
                marginTop: 3,
              }}
            >
              {remaining.toFixed(2)}% remaining
            </div>
          </div>
        );
      })}

      {/* Risk Multiplier */}
      {showMultiplier && (
        <div
          style={{
            paddingTop: 10,
            borderTop: "1px solid #1a1a1a",
          }}
        >
          <div
            style={{
              fontSize: 10,
              color: "#555",
              marginBottom: 8,
            }}
          >
            RISK MULTIPLIER (DD-BASED)
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(5, 1fr)",
              gap: 6,
            }}
          >
            {DD_MULTIPLIER_STEPS.map((step, idx) => {
              const isActive =
                multiplierInfo.label === step.label;
              return (
                <div
                  key={idx}
                  style={{
                    background: isActive
                      ? `${step.color}12`
                      : "#0a0a0a",
                    border: `1px solid ${
                      isActive ? step.color : "#1a1a1a"
                    }`,
                    borderRadius: 6,
                    padding: "6px 8px",
                    textAlign: "center",
                  }}
                >
                  <div
                    style={{ fontSize: 9, color: "#555" }}
                  >
                    {step.label}
                  </div>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 700,
                      color: step.color,
                      marginTop: 2,
                    }}
                  >
                    {step.multiplier === 0
                      ? "STOP"
                      : `${step.multiplier}x`}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default DrawdownMeter;
