"use client";

// ============================================================
// TUYUL FX Wolf-15 — UrgencyRail
// PRD: Command Center — top 3 actionable signals, ranked by urgency
// Compact rail: pair | verdict badge | confidence | RR | expiry | TAKE button
// ============================================================

import Link from "next/link";
import type { L12Verdict, Account } from "@/types";

interface UrgencyRailProps {
  signals: L12Verdict[];
  accounts: Account[];
  onTake: (v: L12Verdict) => void;
}

export default function UrgencyRail({ signals, accounts, onTake }: UrgencyRailProps) {
  if (signals.length === 0) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "12px 14px",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border-accent)",
        borderLeft: "3px solid var(--accent)",
        background: "rgba(26,110,255,0.04)",
      }}
      role="region"
      aria-label="Actionable signals urgency rail"
    >
      {/* Rail header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: "var(--accent)",
            animation: "pulse-dot 1s ease-in-out infinite",
            flexShrink: 0,
          }}
          aria-hidden="true"
        />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 800,
            color: "var(--accent)",
            letterSpacing: "0.10em",
          }}
        >
          ACTIONABLE SIGNALS — TOP {signals.length}
        </span>
        <Link
          href="/trades/signals"
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            color: "var(--text-muted)",
            textDecoration: "none",
            padding: "2px 8px",
            border: "1px solid var(--border-default)",
            borderRadius: 3,
          }}
        >
          SIGNAL BOARD →
        </Link>
      </div>

      {/* Signal rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {signals.map((sig) => {
          const isBuy = String(sig.verdict).includes("BUY");
          const confPct = Math.round((sig.confidence ?? 0) * 100);

          return (
            <div
              key={sig.symbol}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "7px 10px",
                borderRadius: "var(--radius-sm)",
                background: "rgba(0,0,0,0.25)",
                border: "1px solid var(--border-default)",
              }}
            >
              {/* Pair */}
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  fontWeight: 800,
                  color: "var(--text-primary)",
                  minWidth: 70,
                }}
              >
                {sig.symbol}
              </span>

              {/* Verdict badge */}
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  padding: "2px 7px",
                  borderRadius: 3,
                  background: isBuy ? "rgba(0,230,118,0.10)" : "rgba(255,61,87,0.10)",
                  color: isBuy ? "var(--green)" : "var(--red)",
                  border: `1px solid ${isBuy ? "rgba(0,230,118,0.25)" : "rgba(255,61,87,0.25)"}`,
                  flexShrink: 0,
                }}
              >
                {sig.verdict}
              </span>

              {/* Confidence */}
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--text-muted)",
                }}
              >
                CONF {confPct}%
              </span>

              {/* RR */}
              {sig.risk_reward_ratio && (
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                    color:
                      sig.risk_reward_ratio >= 2
                        ? "var(--green)"
                        : "var(--text-secondary)",
                    fontWeight: 600,
                  }}
                >
                  RR {sig.risk_reward_ratio.toFixed(1)}
                </span>
              )}

              {/* Expiry */}
              {sig.expires_at && (
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 9,
                    color: "var(--yellow)",
                    marginLeft: "auto",
                  }}
                >
                  EXP{" "}
                  {new Date(sig.expires_at * 1000).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              )}

              {/* TAKE button */}
              <button
                onClick={() => onTake(sig)}
                disabled={accounts.length === 0}
                style={{
                  padding: "4px 14px",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--accent)",
                  color: "#fff",
                  border: "none",
                  fontSize: 10,
                  fontWeight: 800,
                  letterSpacing: "0.08em",
                  cursor: accounts.length === 0 ? "not-allowed" : "pointer",
                  fontFamily: "var(--font-mono)",
                  opacity: accounts.length === 0 ? 0.4 : 1,
                  flexShrink: 0,
                  marginLeft: sig.expires_at ? 0 : "auto",
                }}
                aria-label={`Take signal for ${sig.symbol}`}
              >
                TAKE
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
