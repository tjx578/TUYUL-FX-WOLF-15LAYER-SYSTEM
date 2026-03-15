"use client";

// ============================================================
// TUYUL FX Wolf-15 — MarketContextCard
// PRD: Command Center right column — market context card
// Shows: session, regime, volatility, trend, active pairs
// ============================================================

import type { ContextSnapshot } from "@/types";

interface MarketContextCardProps {
  context: ContextSnapshot | undefined;
}

const REGIME_COLORS: Record<string, string> = {
  TRENDING: "var(--green)",
  RANGING: "var(--yellow)",
  VOLATILE: "var(--red)",
  BREAKOUT: "var(--accent)",
  RECOVERY: "var(--cyan)",
};

const SESSION_COLORS: Record<string, string> = {
  LONDON: "var(--accent)",
  NEW_YORK: "var(--green)",
  TOKYO: "var(--cyan)",
  SYDNEY: "var(--yellow)",
  OVERLAP: "var(--gold)",
};

function ContextRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        fontSize: 11,
        gap: 8,
      }}
    >
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          fontWeight: 700,
          color: color ?? "var(--text-secondary)",
          letterSpacing: "0.04em",
        }}
      >
        {value}
      </span>
    </div>
  );
}

export default function MarketContextCard({ context }: MarketContextCardProps) {
  if (!context) return null;

  const sessionUpper = context.session?.toUpperCase() ?? "";
  const regimeUpper = context.regime?.toUpperCase() ?? "";

  return (
    <div
      className="panel"
      style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: "var(--text-muted)",
          }}
        >
          MARKET CONTEXT
        </span>
        {context.session && (
          <span
            style={{
              marginLeft: "auto",
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              fontWeight: 800,
              color: SESSION_COLORS[sessionUpper] ?? "var(--text-secondary)",
              padding: "2px 7px",
              borderRadius: 3,
              background: "rgba(255,255,255,0.05)",
              border: "1px solid var(--border-default)",
              letterSpacing: "0.06em",
            }}
          >
            {sessionUpper}
          </span>
        )}
      </div>

      <div style={{ borderTop: "1px solid var(--border-default)" }} />

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {context.regime && (
          <ContextRow
            label="Regime"
            value={regimeUpper}
            color={REGIME_COLORS[regimeUpper] ?? "var(--text-secondary)"}
          />
        )}
        {context.volatility && (
          <ContextRow
            label="Volatility"
            value={context.volatility.toUpperCase()}
            color={
              context.volatility.toUpperCase() === "HIGH"
                ? "var(--red)"
                : context.volatility.toUpperCase() === "LOW"
                ? "var(--text-muted)"
                : "var(--yellow)"
            }
          />
        )}
        {context.trend && (
          <ContextRow
            label="Trend"
            value={context.trend.toUpperCase()}
            color="var(--text-secondary)"
          />
        )}
        {context.active_pairs && context.active_pairs.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span
              style={{
                fontSize: 9,
                color: "var(--text-muted)",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.06em",
              }}
            >
              ACTIVE PAIRS
            </span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {context.active_pairs.slice(0, 8).map((pair) => (
                <span
                  key={pair}
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 9,
                    color: "var(--text-secondary)",
                    padding: "2px 6px",
                    borderRadius: 3,
                    background: "rgba(255,255,255,0.04)",
                    border: "1px solid var(--border-default)",
                    fontWeight: 600,
                  }}
                >
                  {pair}
                </span>
              ))}
              {context.active_pairs.length > 8 && (
                <span
                  style={{
                    fontSize: 9,
                    color: "var(--text-faint)",
                    fontFamily: "var(--font-mono)",
                    padding: "2px 6px",
                  }}
                >
                  +{context.active_pairs.length - 8}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
