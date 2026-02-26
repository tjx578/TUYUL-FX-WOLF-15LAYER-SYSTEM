"use client";

// ============================================================
// TUYUL FX Wolf-15 — VerdictCard
// ============================================================

import type { L12Verdict, VerdictType } from "@/types";
import { formatTime } from "@/lib/timezone";

interface VerdictCardProps {
  verdict: L12Verdict;
  onTake?: () => void;
  onSkip?: () => void;
  selected?: boolean;
}

const VERDICT_COLORS: Record<string, string> = {
  EXECUTE_BUY:  "var(--green)",
  EXECUTE_SELL: "var(--red)",
  EXECUTE:      "var(--green)",
  HOLD:         "var(--yellow)",
  NO_TRADE:     "var(--text-muted)",
  ABORT:        "var(--red)",
};

const VERDICT_BG: Record<string, string> = {
  EXECUTE_BUY:  "rgba(0, 230, 118, 0.07)",
  EXECUTE_SELL: "rgba(255, 61, 87, 0.07)",
  EXECUTE:      "rgba(0, 230, 118, 0.07)",
  HOLD:         "rgba(255, 215, 64, 0.05)",
  NO_TRADE:     "rgba(74, 99, 122, 0.05)",
  ABORT:        "rgba(255, 61, 87, 0.07)",
};

function confidenceLabel(c: number): string {
  if (c >= 0.85) return "VERY HIGH";
  if (c >= 0.7)  return "HIGH";
  if (c >= 0.5)  return "MEDIUM";
  return "LOW";
}

export function VerdictCard({
  verdict,
  onTake,
  onSkip,
  selected,
}: VerdictCardProps) {
  const v = verdict.verdict as string;
  const color = VERDICT_COLORS[v] ?? "var(--text-muted)";
  const bg = VERDICT_BG[v] ?? "transparent";
  const isExecutable = v.startsWith("EXECUTE");
  const confidencePct = Math.round((verdict.confidence ?? 0) * 100);

  return (
    <div
      className="animate-fade-in"
      style={{
        background: selected ? "var(--accent-glow)" : bg,
        border: `1px solid ${selected ? "var(--accent)" : "var(--bg-border)"}`,
        borderRadius: 8,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        cursor: "pointer",
        transition: "all 0.15s ease",
      }}
    >
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          className="num"
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: "var(--text-primary)",
            letterSpacing: "0.04em",
          }}
        >
          {verdict.symbol}
        </span>
        <span
          className="badge"
          style={{
            background: `${color}1a`,
            color,
            borderColor: `${color}40`,
          }}
        >
          {v}
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-muted)",
          }}
        >
          {formatTime(verdict.timestamp * 1000)}
        </span>
      </div>

      {/* ── Direction + prices ── */}
      {isExecutable && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 8,
          }}
        >
          {[
            { label: "ENTRY", value: verdict.entry_price },
            { label: "SL",    value: verdict.stop_loss },
            { label: "TP",    value: verdict.take_profit_1 },
          ].map(({ label, value }) => (
            <div
              key={label}
              style={{
                background: "var(--bg-card)",
                borderRadius: 4,
                padding: "6px 8px",
              }}
            >
              <div
                style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em", marginBottom: 2 }}
              >
                {label}
              </div>
              <div className="num" style={{ fontSize: 13, color: "var(--text-primary)" }}>
                {value?.toFixed(5) ?? "—"}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Confidence bar ── */}
      <div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginBottom: 4,
            fontSize: 10,
            color: "var(--text-muted)",
            letterSpacing: "0.06em",
          }}
        >
          <span>CONFIDENCE</span>
          <span className="num" style={{ color }}>
            {confidencePct}% {confidenceLabel(verdict.confidence ?? 0)}
          </span>
        </div>
        <div className="progress-bar">
          <div
            className="progress-fill"
            style={{
              width: `${confidencePct}%`,
              background:
                confidencePct >= 75 ? "var(--green)" :
                confidencePct >= 50 ? "var(--yellow)" : "var(--red)",
            }}
          />
        </div>
      </div>

      {/* ── Scores row ── */}
      {verdict.scores && (
        <div
          style={{
            display: "flex",
            gap: 8,
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          <span>W:{verdict.scores.wolf_score?.toFixed(0)}</span>
          <span>TII:{verdict.scores.tii_score?.toFixed(0)}</span>
          <span>FRPC:{verdict.scores.frpc_score?.toFixed(0)}</span>
          {verdict.scores.regime && (
            <span className="badge badge-muted" style={{ fontSize: 9, marginLeft: "auto" }}>
              {verdict.scores.regime}
            </span>
          )}
        </div>
      )}

      {/* ── RR ── */}
      {verdict.risk_reward_ratio && (
        <div
          style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}
        >
          <span style={{ color: "var(--text-muted)" }}>R:R</span>
          <span
            className="num"
            style={{
              color:
                verdict.risk_reward_ratio >= 2
                  ? "var(--green)"
                  : "var(--yellow)",
              fontWeight: 700,
            }}
          >
            1:{verdict.risk_reward_ratio.toFixed(2)}
          </span>
        </div>
      )}

      {/* ── Action buttons ── */}
      {isExecutable && (onTake || onSkip) && (
        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          {onTake && (
            <button
              className="btn btn-take"
              style={{ flex: 1 }}
              onClick={(e) => { e.stopPropagation(); onTake(); }}
            >
              ▶ TAKE
            </button>
          )}
          {onSkip && (
            <button
              className="btn btn-skip"
              style={{ flex: 1 }}
              onClick={(e) => { e.stopPropagation(); onSkip(); }}
            >
              ✕ SKIP
            </button>
          )}
        </div>
      )}
    </div>
  );
}
