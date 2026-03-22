"use client";

// ============================================================
// TUYUL FX Wolf-15 — Prices Page (/prices)
// Data: WS /ws/prices + REST fallback
// ============================================================

import { useCallback } from "react";
import { usePricesREST } from "@/lib/api";
import { useLivePrices } from "@/lib/realtime";
import { formatTime } from "@/lib/timezone";
import type { PriceData } from "@/types";

export default function PricesPage() {
  const { data: restPrices, mutate } = usePricesREST();
  const handleSeqGap = useCallback(() => { mutate(); }, [mutate]);
  const { priceMap, status } = useLivePrices(true, false, handleSeqGap);
  const connected = status === "LIVE";

  // Merge WS + REST; WS wins
  const allPrices: PriceData[] = (() => {
    const restMap: Record<string, PriceData> = {};
    for (const p of restPrices ?? []) restMap[p.symbol] = p;
    return Object.values({ ...restMap, ...priceMap });
  })();

  allPrices.sort((a, b) => a.symbol.localeCompare(b.symbol));

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
            PRICE FEED
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Real-time bid/ask per instrument
          </p>
        </div>

        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: connected ? "var(--green)" : "var(--yellow)",
              display: "inline-block",
              animation: connected ? "pulse-dot 1.5s ease-in-out infinite" : "none",
            }}
          />
          {connected ? "REAL-TIME" : "REST POLLING"}
        </div>
      </div>

      {/* ── Price table ── */}
      <div className="panel" style={{ overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              <th>SYMBOL</th>
              <th style={{ textAlign: "right" }}>BID</th>
              <th style={{ textAlign: "right" }}>ASK</th>
              <th style={{ textAlign: "right" }}>SPREAD</th>
              <th style={{ textAlign: "right" }}>24H CHANGE</th>
              <th style={{ textAlign: "right" }}>UPDATED</th>
            </tr>
          </thead>
          <tbody>
            {allPrices.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  style={{
                    textAlign: "center",
                    padding: "32px 0",
                    color: "var(--text-muted)",
                  }}
                >
                  {connected ? "Waiting for price data..." : "Connecting to price feed..."}
                </td>
              </tr>
            ) : (
              allPrices.map((p) => {
                const changeColor =
                  (p.change_percent_24h ?? 0) > 0
                    ? "var(--green)"
                    : (p.change_percent_24h ?? 0) < 0
                      ? "var(--red)"
                      : "var(--text-muted)";

                return (
                  <tr key={p.symbol}>
                    <td>
                      <span
                        style={{ fontWeight: 700, color: "var(--text-primary)", fontSize: 13 }}
                      >
                        {p.symbol}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className="num" style={{ color: "var(--red)", fontSize: 13 }}>
                        {p.bid?.toFixed(5)}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span className="num" style={{ color: "var(--green)", fontSize: 13 }}>
                        {p.ask?.toFixed(5)}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span
                        className="num"
                        style={{
                          fontSize: 12,
                          color:
                            p.spread > 3
                              ? "var(--red)"
                              : "var(--text-secondary)",
                        }}
                      >
                        {p.spread?.toFixed(1)}
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {p.change_percent_24h !== undefined ? (
                        <span
                          className="num"
                          style={{ fontSize: 12, color: changeColor }}
                        >
                          {p.change_percent_24h > 0 ? "+" : ""}
                          {p.change_percent_24h.toFixed(2)}%
                        </span>
                      ) : (
                        <span style={{ color: "var(--text-muted)" }}>—</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <span
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 10,
                          color: "var(--text-muted)",
                        }}
                      >
                        {formatTime(p.timestamp)}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* ── Stats bar ── */}
      <div
        style={{
          display: "flex",
          gap: 20,
          fontSize: 11,
          color: "var(--text-muted)",
          padding: "8px 0",
          borderTop: "1px solid var(--bg-border)",
        }}
      >
        <span>
          Instruments:{" "}
          <span className="num" style={{ color: "var(--text-secondary)" }}>
            {allPrices.length}
          </span>
        </span>
        <span>
          Source:{" "}
          <span style={{ color: connected ? "var(--green)" : "var(--yellow)" }}>
            {connected ? "WebSocket" : "REST"}
          </span>
        </span>
      </div>
    </div>
  );
}
