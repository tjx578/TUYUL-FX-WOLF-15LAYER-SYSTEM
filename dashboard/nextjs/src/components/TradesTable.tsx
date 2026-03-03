"use client";

// ============================================================
// TUYUL FX Wolf-15 — Trades Table (Compact View)
// Used as an alternative tabular view for trades
// ============================================================

import React from "react";

interface Trade {
  trade_id: string;
  pair: string;
  direction: "BUY" | "SELL";
  entry_price: number;
  current_price?: number;
  lot_size: number;
  pnl?: number;
  status: string;
  opened_at: string;
  account_id?: string;
  sl?: number;
  tp?: number;
}

interface TradesTableProps {
  trades: Trade[];
  onSelect?: (trade: Trade) => void;
}

const HEADERS = ["STATUS", "ACCOUNT", "PAIR", "DIR", "LOT", "ENTRY", "SL", "TP", "PnL", "ACTIONS"];

export function TradesTable({ trades, onSelect }: TradesTableProps) {
  if (trades.length === 0) {
    return (
      <div
        style={{
          fontSize: 12,
          color: "var(--text-muted)",
          padding: "24px 0",
          textAlign: "center",
        }}
      >
        No trades to display.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 12,
          fontFamily: "var(--font-mono)",
        }}
      >
        <thead>
          <tr style={{ textAlign: "left" }}>
            {HEADERS.map((h) => (
              <th
                key={h}
                style={{
                  padding: "8px 10px",
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: "0.06em",
                  color: "var(--text-muted)",
                  borderBottom: "1px solid var(--border-subtle)",
                  whiteSpace: "nowrap",
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const pnl = t.pnl ?? 0;
            const pnlColor = pnl >= 0 ? "var(--green, #00F5A0)" : "var(--red, #FF4D4F)";
            const dirColor =
              t.direction === "BUY"
                ? "var(--green, #00F5A0)"
                : "var(--red, #FF4D4F)";

            return (
              <tr
                key={t.trade_id}
                onClick={() => onSelect?.(t)}
                style={{
                  cursor: onSelect ? "pointer" : "default",
                  borderBottom: "1px solid var(--border-subtle, rgba(255,255,255,0.06))",
                }}
              >
                <td style={{ padding: "8px 10px" }}>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 600,
                      letterSpacing: "0.05em",
                      padding: "2px 6px",
                      borderRadius: 4,
                      background: "var(--bg-elevated, #151e2c)",
                      color: "var(--text-muted)",
                    }}
                  >
                    {t.status}
                  </span>
                </td>
                <td style={{ padding: "8px 10px", color: "var(--text-secondary)" }}>
                  {t.account_id ?? "—"}
                </td>
                <td style={{ padding: "8px 10px", fontWeight: 600, color: "var(--text-primary)" }}>
                  {t.pair}
                </td>
                <td style={{ padding: "8px 10px", fontWeight: 700, color: dirColor }}>
                  {t.direction}
                </td>
                <td style={{ padding: "8px 10px", color: "var(--text-secondary)" }}>
                  {t.lot_size.toFixed(2)}
                </td>
                <td style={{ padding: "8px 10px", color: "var(--text-secondary)" }}>
                  {t.entry_price.toFixed(5)}
                </td>
                <td style={{ padding: "8px 10px", color: "var(--text-secondary)" }}>
                  {t.sl?.toFixed(5) ?? "—"}
                </td>
                <td style={{ padding: "8px 10px", color: "var(--text-secondary)" }}>
                  {t.tp?.toFixed(5) ?? "—"}
                </td>
                <td style={{ padding: "8px 10px", fontWeight: 700, color: pnlColor }}>
                  {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}
                </td>
                <td style={{ padding: "8px 10px" }}>
                  <button
                    style={{
                      fontSize: 10,
                      padding: "2px 8px",
                      borderRadius: 4,
                      border: "1px solid var(--border-subtle)",
                      background: "transparent",
                      color: "var(--text-muted)",
                      cursor: "pointer",
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelect?.(t);
                    }}
                  >
                    VIEW
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default TradesTable;
