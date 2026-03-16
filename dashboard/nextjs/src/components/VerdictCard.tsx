"use client";

// ============================================================
// TUYUL FX Wolf-15 — VerdictCard
// Gate glow + breakdowns use CSS transitions (no framer-motion).
// ============================================================

import type { L12Verdict, VerdictType } from "@/types";
import { formatTime } from "@/lib/timezone";
import Panel from "@/components/ui/Panel";
import StatusBadge from "@/components/ui/StatusBadge";
import Button from "@/components/ui/Button";
import { useLivePulse } from "@/hooks/useLivePulse";

interface VerdictCardProps {
  verdict: L12Verdict;
  onTake?: () => void;
  onSkip?: () => void;
  selected?: boolean;
}

const VERDICT_COLORS: Record<string, string> = {
  EXECUTE_BUY: "var(--green)",
  EXECUTE_SELL: "var(--red)",
  EXECUTE: "var(--green)",
  HOLD: "var(--yellow)",
  NO_TRADE: "var(--text-muted)",
  ABORT: "var(--red)",
};

function confidenceLabel(c: number): string {
  if (c >= 0.85) return "VERY HIGH";
  if (c >= 0.7) return "HIGH";
  if (c >= 0.5) return "MEDIUM";
  return "LOW";
}

function verdictGlow(v: string, selected: boolean): "cyan" | "emerald" | "orange" | "none" {
  if (selected) return "cyan";
  if (v.startsWith("EXECUTE")) return "emerald";
  if (v === "ABORT") return "orange";
  return "none";
}

function verdictBadgeType(v: string): "execute" | "hold" | "no-trade" | "abort" {
  if (v.startsWith("EXECUTE")) return "execute";
  if (v === "HOLD") return "hold";
  if (v === "ABORT") return "abort";
  return "no-trade";
}

export function VerdictCard({
  verdict,
  onTake,
  onSkip,
  selected,
}: VerdictCardProps) {
  const v = verdict.verdict as string;
  const color = VERDICT_COLORS[v] ?? "var(--text-muted)";
  const isExecutable = v.startsWith("EXECUTE");
  const confidencePct = Math.round((verdict.confidence ?? 0) * 100);
  const verdictPulse = useLivePulse(v);
  const confidencePulse = useLivePulse(confidencePct);
  const pulse = verdictPulse || confidencePulse;

  return (
    <Panel
      glow={verdictGlow(v, selected ?? false)}
      className={`animate-fade-in flex flex-col gap-3 cursor-pointer transition-all duration-150${pulse ? " live-pulse" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`${verdict.symbol} verdict: ${v}, confidence ${confidencePct}%`}
    >
      {/* ── Header ── */}
      <div className="flex items-center gap-2">
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
        <StatusBadge type={verdictBadgeType(v)} label={v} />
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
            { label: "SL", value: verdict.stop_loss },
            { label: "TP", value: verdict.take_profit_1 },
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

      {/* ── Gate Sequential Glow Engine ── */}
      {verdict.scores && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          {([
            { label: "W", value: verdict.scores.wolf_score },
            { label: "TII", value: verdict.scores.tii_score },
            { label: "FRPC", value: verdict.scores.frpc_score },
          ] as { label: string; value: number | undefined }[]).map(({ label, value }, index) => {
            const threshold = label === "W" ? 22 : label === "TII" ? 0.75 : 0.70;
            const passing = (value ?? 0) >= threshold;
            return (
              <div
                key={label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "3px 7px",
                  borderRadius: 6,
                  background: passing ? "rgba(0,245,160,0.08)" : "rgba(255,255,255,0.04)",
                  border: `1px solid ${passing ? "rgba(0,245,160,0.25)" : "rgba(255,255,255,0.08)"}`,
                  transition: "background 0.3s ease, border-color 0.3s ease",
                }}
              >
                <div
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: passing ? "var(--green)" : "var(--text-muted)",
                    boxShadow: passing ? "0 0 6px rgba(0,245,160,0.8)" : "none",
                    opacity: passing ? 1 : 0.3,
                    transition: "opacity 0.3s ease, background 0.3s ease, box-shadow 0.3s ease",
                  }}
                />
                <span style={{
                  fontSize: 9,
                  fontFamily: "var(--font-mono)",
                  color: passing ? "var(--green)" : "var(--text-muted)",
                  letterSpacing: "0.06em",
                }}>
                  {label}:{value?.toFixed(0) ?? "—"}
                </span>
              </div>
            );
          })}
          {verdict.scores.regime && (
            <span
              className="badge badge-muted"
              style={{ fontSize: 9, marginLeft: "auto" }}
            >
              {verdict.scores.regime}
            </span>
          )}
        </div>
      )}

      {/* ── Wolf 30-Point Breakdown ── */}
      {verdict.scores?.f_score != null && (
        <div
          style={{
            display: "flex",
            gap: 4,
            fontSize: 9,
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
            letterSpacing: "0.04em",
          }}
        >
          {([
            { label: "F", value: verdict.scores.f_score, max: 8 },
            { label: "T", value: verdict.scores.t_score, max: 12 },
            { label: "FTA", value: verdict.scores.fta_score, max: 5 },
            { label: "E", value: verdict.scores.exec_score, max: 5 },
          ] as { label: string; value: number | undefined; max: number }[]).map(({ label, value, max }) => (
            <span key={label} style={{ opacity: (value ?? 0) >= max * 0.7 ? 1 : 0.6 }}>
              {label}:{value ?? 0}/{max}
            </span>
          ))}
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
            <Button
              variant="take"
              style={{ flex: 1 }}
              onClick={(e) => { e.stopPropagation(); onTake(); }}
            >
              ▶ TAKE
            </Button>
          )}
          {onSkip && (
            <Button
              variant="skip"
              style={{ flex: 1 }}
              onClick={(e) => { e.stopPropagation(); onSkip(); }}
            >
              ✕ SKIP
            </Button>
          )}
        </div>
      )}
    </Panel>
  );
}
