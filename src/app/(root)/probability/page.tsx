"use client";

// ============================================================
// TUYUL FX Wolf-15 — Probability Monitor Page (/probability)
// Data: /api/v1/probability/summary + /calibration
// ============================================================

import {
  useProbabilitySummary,
  useProbabilityCalibration,
} from "@/shared/api/market.api";

const GRADE_COLOR: Record<string, string> = {
  A: "var(--green)",
  B: "var(--green)",
  C: "var(--yellow)",
  D: "var(--yellow)",
  F: "var(--red)",
};

export default function ProbabilityPage() {
  const { data: summary, isLoading: sumLoading } = useProbabilitySummary();
  const { data: calibration } = useProbabilityCalibration();

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* ── Header ── */}
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
          PROBABILITY MONITOR
        </h1>
        <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
          L7 Monte Carlo + Bayesian confidence health
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* ── MC / Bayesian summary ── */}
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.1em",
              color: "var(--text-muted)",
            }}
          >
            TODAY&apos;S PROBABILITY SUMMARY
          </div>

          {sumLoading ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Loading...
            </div>
          ) : summary ? (
            <>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: 12,
                }}
              >
                <ProbStat
                  label="TOTAL SIGNALS"
                  value={summary.total_signals_today}
                />
                <ProbStat
                  label="HIGH CONFIDENCE"
                  value={summary.high_confidence_signals}
                  color="var(--green)"
                />
                <ProbStat
                  label="AVG MC WIN %"
                  value={`${(summary.avg_mc_win_prob * 100).toFixed(1)}%`}
                  color={
                    summary.avg_mc_win_prob >= 0.6
                      ? "var(--green)"
                      : "var(--yellow)"
                  }
                />
                <ProbStat
                  label="AVG BAYESIAN"
                  value={`${(summary.avg_bayesian_confidence * 100).toFixed(1)}%`}
                  color={
                    summary.avg_bayesian_confidence >= 0.65
                      ? "var(--green)"
                      : "var(--yellow)"
                  }
                />
                <ProbStat
                  label="LOW CONFIDENCE"
                  value={summary.low_confidence_signals}
                  color="var(--red)"
                />
                <ProbStat
                  label="CALIBRATION"
                  value={summary.calibration_grade}
                  color={GRADE_COLOR[summary.calibration_grade] ?? "var(--text-muted)"}
                  large
                />
              </div>

              {/* MC win probability gauge */}
              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 10,
                    color: "var(--text-muted)",
                    marginBottom: 4,
                  }}
                >
                  <span>MC WIN PROBABILITY</span>
                  <span className="num" style={{ color: "var(--green)" }}>
                    {(summary.avg_mc_win_prob * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{
                      width: `${summary.avg_mc_win_prob * 100}%`,
                      background:
                        summary.avg_mc_win_prob >= 0.6
                          ? "var(--green)"
                          : summary.avg_mc_win_prob >= 0.4
                            ? "var(--yellow)"
                            : "var(--red)",
                    }}
                  />
                </div>
              </div>

              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 10,
                    color: "var(--text-muted)",
                    marginBottom: 4,
                  }}
                >
                  <span>BAYESIAN CONFIDENCE</span>
                  <span className="num" style={{ color: "var(--blue)" }}>
                    {(summary.avg_bayesian_confidence * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{
                      width: `${summary.avg_bayesian_confidence * 100}%`,
                      background: "var(--blue)",
                    }}
                  />
                </div>
              </div>
            </>
          ) : (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              No probability data available.
            </div>
          )}
        </div>

        {/* ── Calibration ── */}
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.1em",
              color: "var(--text-muted)",
            }}
          >
            CALIBRATION REPORT
          </div>

          {calibration ? (
            <>
              {/* Big grade display */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  padding: 20,
                  background: "var(--bg-panel)",
                  borderRadius: 8,
                  gap: 6,
                }}
              >
                <span
                  style={{
                    fontSize: 64,
                    fontFamily: "var(--font-mono)",
                    fontWeight: 700,
                    color: GRADE_COLOR[calibration.grade] ?? "var(--text-muted)",
                    lineHeight: 1,
                  }}
                >
                  {calibration.grade}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    letterSpacing: "0.08em",
                  }}
                >
                  CALIBRATION GRADE
                </span>
                <span
                  className="num"
                  style={{
                    fontSize: 16,
                    fontWeight: 600,
                    color: GRADE_COLOR[calibration.grade] ?? "var(--text-muted)",
                  }}
                >
                  {(calibration.score * 100).toFixed(1)}%
                </span>
              </div>

              {/* Details */}
              {calibration.details && calibration.details.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.08em", marginBottom: 2 }}>
                    DETAILS
                  </div>
                  {calibration.details.map((d: string, i: number) => (
                    <div
                      key={i}
                      style={{
                        fontSize: 12,
                        color: "var(--text-secondary)",
                        padding: "4px 8px",
                        background: "var(--bg-panel)",
                        borderRadius: 4,
                      }}
                    >
                      {d}
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              No calibration data available.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ProbStat({
  label,
  value,
  color = "var(--text-primary)",
  large = false,
}: {
  label: string;
  value: string | number;
  color?: string;
  large?: boolean;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 9,
          color: "var(--text-muted)",
          letterSpacing: "0.08em",
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div
        className="num"
        style={{
          fontSize: large ? 22 : 15,
          fontWeight: 700,
          color,
        }}
      >
        {value}
      </div>
    </div>
  );
}
