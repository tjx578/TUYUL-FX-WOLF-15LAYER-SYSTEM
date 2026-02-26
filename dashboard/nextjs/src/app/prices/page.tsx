"use client";

// ============================================================
// TUYUL FX Wolf-15 — Prices Page (/prices)
// Real-time price ticker + candle chart
// ============================================================

import { usePricesREST } from "@/lib/api";
import { usePriceMap } from "@/lib/websocket";

export default function PricesPage() {
  const { data: restPrices, isLoading } = usePricesREST();
  const { priceMap: wsPrices, connected } = usePriceMap();

  // Merge: WS prices take priority over REST
  const prices: Record<string, { bid: number; ask: number; spread: number; ts: string }> = {};
  if (restPrices) {
    for (const [k, v] of Object.entries(restPrices)) {
      prices[k] = v as any;
    }
  }
  if (wsPrices) {
    for (const [k, v] of Object.entries(wsPrices as Record<string, any>)) {
      prices[k] = v;
    }
  }

  const pairs = Object.keys(prices).sort();

  return (
    <div style={{ padding: "2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ color: "var(--accent)", fontFamily: "var(--font-display)", fontSize: "1.5rem" }}>
          ◭ LIVE PRICES
        </h1>
        <span style={{
          fontSize: "0.75rem",
          color: connected ? "var(--green)" : "var(--red)",
        }}>
          {connected ? "● WS Connected" : "○ WS Disconnected"}
        </span>
      </div>

      {isLoading && <p style={{ color: "var(--text-muted)" }}>Loading prices…</p>}

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
        gap: "0.75rem",
      }}>
        {pairs.map((pair) => {
          const p = prices[pair];
          return (
            <div key={pair} style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: "1rem",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}>
              <div>
                <p style={{ fontFamily: "var(--font-display)", fontSize: "1rem", color: "var(--text-primary)" }}>
                  {pair}
                </p>
                <p style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
                  spread: {p.spread?.toFixed(1) ?? "—"}
                </p>
              </div>
              <div style={{ textAlign: "right" }}>
                <p style={{ fontFamily: "var(--font-mono)", fontSize: "0.95rem", color: "var(--green)" }}>
                  {p.bid?.toFixed(5) ?? "—"}
                </p>
                <p style={{ fontFamily: "var(--font-mono)", fontSize: "0.95rem", color: "var(--red)" }}>
                  {p.ask?.toFixed(5) ?? "—"}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {!isLoading && pairs.length === 0 && (
        <p style={{ color: "var(--text-muted)", textAlign: "center", marginTop: "3rem" }}>
          No price data available
        </p>
      )}
    </div>
  );
}
