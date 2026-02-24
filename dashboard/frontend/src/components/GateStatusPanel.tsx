"use client";

/**
 * GateStatusPanel — 9-Gate Constitutional Status Display
 *
 * Shows all 9 gates that must PASS for L12 EXECUTE verdict:
 * 1. TII Symmetry ≥ 0.85
 * 2. Integrity Index ≥ 0.80
 * 3. Risk:Reward ≥ 2.0
 * 4. FTA Score ≥ 3
 * 5. Monte Carlo WR ≥ 55%
 * 6. PropFirm Compliant = true
 * 7. Drawdown ≤ 5%
 * 8. Latency ≤ 200ms
 * 9. Confidence (conf12) ≥ 0.70
 *
 * Props:
 *   gates: GateResult[] (from L12 pipeline output)
 */

import React, { useMemo } from "react";

// ── Types ───────────────────────────────────────────────────────

export interface GateResult {
  id: number;
  name: string;
  key: string;
  value: number | boolean;
  threshold: number | boolean;
  operator: ">=" | "<=" | "=";
  passed: boolean;
}

interface GateStatusPanelProps {
  gates: GateResult[];
  showHeader?: boolean;
}

// ── Constants ───────────────────────────────────────────────────

const GREEN = "#10b981";
const RED = "#ef4444";
const GOLD = "#d4af37";

// ── Component ───────────────────────────────────────────────────

export function GateStatusPanel({
  gates,
  showHeader = true,
}: GateStatusPanelProps): React.ReactElement {
  const { passed, total } = useMemo(() => {
    return {
      passed: gates.filter((g) => g.passed).length,
      total: gates.length,
    };
  }, [gates]);

  const allPassed = passed === total;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Header */}
      {showHeader && (
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
                background: allPassed ? GREEN : RED,
                boxShadow: `0 0 6px ${allPassed ? GREEN : RED}66`,
              }}
            />
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: allPassed ? GREEN : RED,
              }}
            >
              {allPassed
                ? "ALL GATES PASS"
                : `${total - passed} GATE(S) BLOCKED`}
            </span>
          </div>
          <span
            style={{
              fontSize: 18,
              fontWeight: 800,
              color: allPassed ? GOLD : RED,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {passed}/{total}
          </span>
        </div>
      )}

      {/* Gate list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {gates.map((gate) => {
          const displayValue =
            typeof gate.value === "boolean"
              ? gate.value
                ? "OK"
                : "FAIL"
              : typeof gate.value === "number"
                ? gate.value % 1 === 0
                  ? gate.value.toString()
                  : gate.value.toFixed(
                      gate.value < 10 ? 2 : 1
                    )
                : String(gate.value);

          const displayThreshold =
            typeof gate.threshold === "boolean"
              ? "OK"
              : typeof gate.threshold === "number"
                ? gate.threshold % 1 === 0
                  ? gate.threshold.toString()
                  : gate.threshold.toFixed(
                      gate.threshold < 10 ? 2 : 1
                    )
                : String(gate.threshold);

          return (
            <div
              key={gate.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "7px 10px",
                borderRadius: 6,
                background: gate.passed
                  ? `${GREEN}08`
                  : `${RED}08`,
                border: `1px solid ${
                  gate.passed ? GREEN : RED
                }15`,
                transition: "all 0.3s",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    fontSize: 12,
                    color: gate.passed ? GREEN : RED,
                    width: 14,
                  }}
                >
                  {gate.passed ? "✓" : "✗"}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    color: "#555",
                    width: 16,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {gate.id}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: gate.passed ? "#ccc" : "#888",
                  }}
                >
                  {gate.name}
                </span>
              </div>
              <span
                style={{
                  fontSize: 11,
                  fontVariantNumeric: "tabular-nums",
                  color: gate.passed ? GREEN : RED,
                  fontWeight: 600,
                  fontFamily: "monospace",
                }}
              >
                {displayValue} {gate.operator} {displayThreshold}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default GateStatusPanel;
