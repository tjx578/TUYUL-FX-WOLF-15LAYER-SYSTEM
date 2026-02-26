"use client";

// ============================================================
// TUYUL FX Wolf-15 — Active Trades Page (/trades)
// Data: useActiveTrades + WS /ws/trades
// ============================================================

import { useActiveTrades } from "@/lib/api";
import { TradeCard } from "@/components/TradeCard";
import { useTradesWS } from "@/lib/websocket";
import { TradeStatus } from "@/types";

export default function TradesPage() {
  const { data: trades, mutate, isLoading } = useActiveTrades();
  const { connected } = useTradesWS();

  const open      = (trades ?? []).filter((t) => t.status === TradeStatus.OPEN);
  const intended  = (trades ?? []).filter((t) => t.status === TradeStatus.INTENDED);
  const pending   = (trades ?? []).filter((t) => t.status === TradeStatus.PENDING);
  const closed    = (trades ?? []).filter((t) => t.status === TradeStatus.CLOSED || t.status === TradeStatus.CANCELLED);

  const totalPnl = open.reduce((sum, t) => sum + (t.pnl ?? 0), 0);

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
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
            ACTIVE TRADES
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Trade lifecycle: INTENDED → PENDING → OPEN → CLOSED
          </p>
        </div>

        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          {/* WS indicator */}
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: connected ? "var(--green)" : "var(--red)",
                display: "inline-block",
              }}
            />
            <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
              {connected ? "LIVE" : "REST"}
            </span>
          </div>

          {/* Floating PnL */}
          {open.length > 0 && (
            <span
              className="num"
              style={{
                fontSize: 14,
                fontWeight: 700,
                color: totalPnl >= 0 ? "var(--green)" : "var(--red)",
              }}
            >
              Float: {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)}
            </span>
          )}

          <button
            className="btn btn-ghost"
            style={{ fontSize: 11 }}
            onClick={() => mutate()}
          >
            ↻
          </button>
        </div>
      </div>

      {isLoading ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 16 }}>
          Loading trades...
        </div>
      ) : (trades ?? []).length === 0 ? (
        <div
          style={{
            fontSize: 12,
            color: "var(--text-muted)",
            padding: "48px 0",
            textAlign: "center",
            background: "var(--bg-panel)",
            borderRadius: 8,
          }}
        >
          No active trades. Go to{" "}
          <a href="/trades/signals" style={{ color: "var(--accent)" }}>
            Signal Queue
          </a>{" "}
          to take a signal.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* ── INTENDED (need confirm) ── */}
          {intended.length > 0 && (
            <Section
              title="INTENDED"
              subtitle="Awaiting broker confirmation"
              color="var(--yellow)"
              count={intended.length}
            >
              {intended.map((t) => (
                <TradeCard key={t.trade_id} trade={t} onUpdate={() => mutate()} />
              ))}
            </Section>
          )}

          {/* ── OPEN ── */}
          {open.length > 0 && (
            <Section
              title="OPEN"
              subtitle="Live positions"
              color="var(--green)"
              count={open.length}
            >
              {open.map((t) => (
                <TradeCard key={t.trade_id} trade={t} onUpdate={() => mutate()} />
              ))}
            </Section>
          )}

          {/* ── PENDING ── */}
          {pending.length > 0 && (
            <Section
              title="PENDING"
              subtitle="Order placed, awaiting fill"
              color="var(--blue)"
              count={pending.length}
            >
              {pending.map((t) => (
                <TradeCard key={t.trade_id} trade={t} onUpdate={() => mutate()} />
              ))}
            </Section>
          )}

          {/* ── CLOSED / CANCELLED ── */}
          {closed.length > 0 && (
            <Section
              title="CLOSED"
              subtitle="Completed trades"
              color="var(--text-muted)"
              count={closed.length}
              collapsed
            >
              {closed.map((t) => (
                <TradeCard key={t.trade_id} trade={t} onUpdate={() => mutate()} />
              ))}
            </Section>
          )}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  subtitle,
  color,
  count,
  collapsed = false,
  children,
}: {
  title: string;
  subtitle: string;
  color: string;
  count: number;
  collapsed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 10,
          paddingBottom: 8,
          borderBottom: `1px solid ${color}30`,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: color,
            display: "inline-block",
            boxShadow: `0 0 8px ${color}`,
          }}
        />
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.08em",
            color,
          }}
        >
          {title}
        </span>
        <span
          className="badge"
          style={{
            background: `${color}1a`,
            color,
            borderColor: `${color}40`,
            fontSize: 9,
          }}
        >
          {count}
        </span>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          {subtitle}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {children}
      </div>
    </div>
  );
}
