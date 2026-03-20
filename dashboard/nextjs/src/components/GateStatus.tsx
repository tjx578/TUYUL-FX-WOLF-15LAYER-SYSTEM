"use client";

// ============================================================
// TUYUL FX Wolf-15 — GateStatus (9-gate constitutional check)
// ============================================================

import type { GateCheck } from "@/types";

interface GateStatusProps {
  gates: GateCheck[];
  compact?: boolean;
}

export function GateStatus({ gates, compact = false }: GateStatusProps) {
  const passed = gates.filter((g) => g.passed).length;
  const allPassed = passed === gates.length;

  if (compact) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          className="num"
          style={{
            fontSize: 11,
            color: allPassed ? "var(--green)" : "var(--yellow)",
          }}
        >
          {passed}/{gates.length}
        </span>
        <div style={{ display: "flex", gap: 3 }}>
          {gates.map((g) => (
            <span
              key={g.gate_id}
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: g.passed ? "var(--green)" : "var(--red)",
                display: "inline-block",
              }}
              title={g.name}
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 6,
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: "0.06em",
          color: "var(--text-muted)",
        }}
      >
        <span>GATE CHECKS</span>
        <span
          style={{ color: allPassed ? "var(--green)" : "var(--yellow)" }}
        >
          {passed}/{gates.length} PASSED
        </span>
      </div>

      {gates.map((gate) => (
        <div
          key={gate.gate_id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "5px 8px",
            borderRadius: 4,
            background: gate.passed
              ? "rgba(0,230,118,0.05)"
              : "rgba(255,61,87,0.05)",
            border: `1px solid ${gate.passed ? "rgba(0,230,118,0.1)" : "rgba(255,61,87,0.1)"}`,
          }}
        >
          <span
            style={{
              fontSize: 12,
              color: gate.passed ? "var(--green)" : "var(--red)",
            }}
          >
            {gate.passed ? "✓" : "✗"}
          </span>
          <span
            style={{
              flex: 1,
              fontSize: 11,
              color: gate.passed ? "var(--text-secondary)" : "var(--text-muted)",
            }}
          >
            {gate.name || gate.gate_id}
          </span>
          {gate.message && (
            <span
              className="num"
              style={{
                fontSize: 10,
                color: "var(--text-muted)",
              }}
            >
              {gate.message}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
