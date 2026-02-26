"use client";

// ============================================================
// TUYUL FX Wolf-15 — Probability Page (/probability)
// Shows probability calibration & per-signal probability
// ============================================================

import { useProbabilitySummary, useProbabilityCalibration } from "@/lib/api";

export default function ProbabilityPage() {
  const { data: summary, isLoading: sLoad } = useProbabilitySummary();
  const { data: calibration, isLoading: cLoad } = useProbabilityCalibration();

  const isLoading = sLoad || cLoad;

  return (
    <div style={{ padding: "2rem" }}>
      <h1 style={{ color: "var(--accent)", fontFamily: "var(--font-display)", fontSize: "1.5rem", marginBottom: "1.5rem" }}>
        ◫ PROBABILITY ENGINE
      </h1>

      {isLoading && <p style={{ color: "var(--text-muted)" }}>Loading probability data…</p>}

      {/* Summary Section */}
      {summary && (
        <div style={{
          background: "var(--bg-card)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: "1.25rem",
          marginBottom: "1.5rem",
        }}>
          <h2 style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)", marginBottom: "1rem" }}>
            Summary
          </h2>
          <pre style={{
            fontFamily: "var(--font-mono)",
            fontSize: "0.8rem",
            color: "var(--text-muted)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}>
            {JSON.stringify(summary, null, 2)}
          </pre>
        </div>
      )}

      {/* Calibration Section */}
      {calibration && (
        <div style={{
          background: "var(--bg-card)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: "1.25rem",
        }}>
          <h2 style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)", marginBottom: "1rem" }}>
            Calibration
          </h2>
          <pre style={{
            fontFamily: "var(--font-mono)",
            fontSize: "0.8rem",
            color: "var(--text-muted)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}>
            {JSON.stringify(calibration, null, 2)}
          </pre>
        </div>
      )}

      {!isLoading && !summary && !calibration && (
        <p style={{ color: "var(--text-muted)", textAlign: "center", marginTop: "3rem" }}>
          No probability data available yet
        </p>
      )}
    </div>
  );
}
