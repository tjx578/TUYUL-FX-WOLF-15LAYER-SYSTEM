"use client";

/**
 * TUYUL FX Wolf-15 — Realtime Charts Page
 *
 * High-impact visual terminal for traders.
 * Displays live candlestick charts with realtime updates.
 */

import { useState, useMemo } from "react";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { DataFreshnessBadge } from "@/components/realtime/DataFreshnessBadge";
import { useLiveCandles } from "@/lib/realtime/hooks/useLiveCandles";

// Available symbols and timeframes
const SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "GBPJPY", "AUDUSD"];
const TIMEFRAMES = [
  { value: "M1", label: "1M", intervalMs: 60_000 },
  { value: "M5", label: "5M", intervalMs: 300_000 },
  { value: "M15", label: "15M", intervalMs: 900_000 },
  { value: "H1", label: "1H", intervalMs: 3600_000 },
];

export default function ChartsPage() {
  const [selectedSymbol, setSelectedSymbol] = useState("EURUSD");
  const [selectedTimeframe, setSelectedTimeframe] = useState("M1");

  const { candles, forming, status, isStale } = useLiveCandles(selectedSymbol);

  // Calculate lastUpdatedAt from forming candle or latest closed candle
  const lastUpdatedAt = useMemo(() => {
    if (forming?.timestamp) return forming.timestamp;
    if (candles.length > 0) return candles[candles.length - 1].timestamp;
    return null;
  }, [forming, candles]);

  const connected = status === "LIVE";

  return (
    <div style={{ padding: "22px 26px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div
            style={{
              fontSize: 20,
              fontWeight: 900,
              letterSpacing: "0.06em",
              color: "var(--text-primary)",
            }}
          >
            REALTIME CHARTS
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Live candlestick visualization with realtime updates
          </div>
        </div>

        <DataFreshnessBadge
          lastUpdatedAt={lastUpdatedAt}
          connected={connected}
          staleThresholdSec={5}
        />
      </div>

      {/* Controls */}
      <div
        style={{
          display: "flex",
          gap: 16,
          flexWrap: "wrap",
          alignItems: "center",
          padding: "14px 16px",
          borderRadius: 12,
          background: "var(--bg-card, rgba(255,255,255,0.02))",
          border: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        {/* Symbol selector */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 9,
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.1em",
              color: "var(--text-muted)",
            }}
          >
            SYMBOL
          </span>
          <div style={{ display: "flex", gap: 4 }}>
            {SYMBOLS.map((sym) => (
              <button
                key={sym}
                onClick={() => setSelectedSymbol(sym)}
                style={{
                  padding: "8px 12px",
                  borderRadius: 8,
                  border: "1px solid rgba(255,255,255,0.10)",
                  background:
                    selectedSymbol === sym
                      ? "rgba(0,245,160,0.12)"
                      : "transparent",
                  color:
                    selectedSymbol === sym
                      ? "var(--green)"
                      : "var(--text-muted)",
                  fontSize: 10,
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.08em",
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
              >
                {sym}
              </button>
            ))}
          </div>
        </div>

        {/* Timeframe selector */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 9,
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.1em",
              color: "var(--text-muted)",
            }}
          >
            TIMEFRAME
          </span>
          <div style={{ display: "flex", gap: 4 }}>
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.value}
                onClick={() => setSelectedTimeframe(tf.value)}
                style={{
                  padding: "8px 12px",
                  borderRadius: 8,
                  border: "1px solid rgba(255,255,255,0.10)",
                  background:
                    selectedTimeframe === tf.value
                      ? "rgba(0,229,255,0.12)"
                      : "transparent",
                  color:
                    selectedTimeframe === tf.value
                      ? "var(--accent)"
                      : "var(--text-muted)",
                  fontSize: 10,
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.08em",
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>

        {/* Connection status */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <span
            style={{
              fontSize: 9,
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.08em",
              color: "var(--text-muted)",
            }}
          >
            WS:
          </span>
          <span
            style={{
              fontSize: 9,
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.08em",
              fontWeight: 600,
              color:
                status === "LIVE"
                  ? "var(--green)"
                  : status === "CONNECTING" || status === "RECONNECTING"
                    ? "var(--yellow, #FFB800)"
                    : "var(--red)",
            }}
          >
            {status}
          </span>

          <span
            className="badge badge-muted"
            style={{ fontSize: 9, letterSpacing: "0.08em" }}
          >
            {candles.length} CANDLES
          </span>
        </div>
      </div>

      {/* Chart */}
      <CandlestickChart
        symbol={selectedSymbol}
        timeframe={selectedTimeframe}
        data={candles}
        forming={forming}
        height={480}
      />

      {/* Info panel */}
      {isStale && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: 10,
            background: "rgba(255,184,0,0.08)",
            border: "1px solid rgba(255,184,0,0.2)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "var(--yellow, #FFB800)",
            }}
          />
          <span
            style={{
              fontSize: 11,
              color: "var(--yellow, #FFB800)",
            }}
          >
            Candle data may be stale. Waiting for backend to push new updates...
          </span>
        </div>
      )}

      {/* Stats row */}
      {candles.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: 12,
          }}
        >
          <StatCard
            label="LATEST CLOSE"
            value={candles[candles.length - 1]?.close.toFixed(5) ?? "-"}
          />
          <StatCard
            label="HIGH"
            value={Math.max(...candles.slice(-50).map((c) => c.high)).toFixed(5)}
            color="var(--green)"
          />
          <StatCard
            label="LOW"
            value={Math.min(...candles.slice(-50).map((c) => c.low)).toFixed(5)}
            color="var(--red)"
          />
          <StatCard
            label="CANDLE COUNT"
            value={candles.length.toString()}
          />
        </div>
      )}
    </div>
  );
}

function StatCard({
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
        padding: "14px 16px",
        borderRadius: 10,
        background: "var(--bg-card, rgba(255,255,255,0.02))",
        border: "1px solid rgba(255,255,255,0.06)",
      }}
    >
      <div
        style={{
          fontSize: 9,
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.1em",
          color: "var(--text-muted)",
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 16,
          fontWeight: 700,
          fontFamily: "var(--font-mono)",
          color: color ?? "var(--text-primary)",
        }}
      >
        {value}
      </div>
    </div>
  );
}
