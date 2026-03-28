"use client";

// ============================================================
// TUYUL FX Wolf-15 — Trade Card Component
// Used by: /trades page
// ============================================================

import { useState } from "react";
import type { Trade } from "@/types";
import { TradeStatus } from "@/types";
import { confirmTrade, closeTrade } from "@/features/trades/api/tradesQuery.api";

const STATUS_COLOR: Record<string, string> = {
  [TradeStatus.INTENDED]: "var(--yellow)",
  [TradeStatus.PENDING]: "var(--blue)",
  [TradeStatus.OPEN]: "var(--green)",
  [TradeStatus.CLOSED]: "var(--text-muted)",
  [TradeStatus.CANCELLED]: "var(--text-muted)",
  [TradeStatus.SKIPPED]: "var(--text-muted)",
};

interface TradeCardProps {
  trade: Trade;
  onUpdate: () => void;
}

export function TradeCard({ trade, onUpdate }: TradeCardProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const color = STATUS_COLOR[trade.status] ?? "var(--text-muted)";

  const handleConfirm = async () => {
    setLoading(true);
    setError(null);
    try {
      await confirmTrade(trade.trade_id);
      onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to confirm trade");
    } finally {
      setLoading(false);
    }
  };

  const handleClose = async () => {
    setLoading(true);
    setError(null);
    try {
      await closeTrade(trade.trade_id, "MANUAL_CLOSE");
      onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to close trade");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="card"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "12px 16px",
        borderLeft: `3px solid ${color}`,
      }}
    >
      {/* Direction badge */}
      <div
        style={{
          minWidth: 44,
          textAlign: "center",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.06em",
          color: trade.direction === "BUY" ? "var(--green)" : "var(--red)",
          background:
            trade.direction === "BUY"
              ? "rgba(0,255,136,0.08)"
              : "rgba(255,68,68,0.08)",
          borderRadius: 4,
          padding: "3px 8px",
        }}
      >
        {trade.direction}
      </div>

      {/* Pair + info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: "var(--text-primary)",
            }}
          >
            {trade.pair}
          </span>
          <span
            className="badge"
            style={{
              fontSize: 9,
              background: `${color}1a`,
              color,
              borderColor: `${color}40`,
            }}
          >
            {trade.status}
          </span>
          <span
            style={{
              fontSize: 10,
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            {trade.lot_size} lot
          </span>
        </div>

        <div
          style={{
            display: "flex",
            gap: 12,
            marginTop: 4,
            fontSize: 10,
            color: "var(--text-muted)",
          }}
        >
          <span>
            Entry:{" "}
            <span className="num" style={{ color: "var(--text-secondary)" }}>
              {trade.entry_price?.toFixed(5)}
            </span>
          </span>
          <span>
            SL:{" "}
            <span className="num" style={{ color: "var(--red)" }}>
              {trade.stop_loss?.toFixed(5)}
            </span>
          </span>
          <span>
            TP:{" "}
            <span className="num" style={{ color: "var(--green)" }}>
              {trade.take_profit?.toFixed(5)}
            </span>
          </span>
          <span>
            Risk:{" "}
            <span className="num" style={{ color: "var(--yellow)" }}>
              {trade.total_risk_percent?.toFixed(1)}%
            </span>
          </span>
        </div>
      </div>

      {/* PnL (for open trades) */}
      {trade.status === TradeStatus.OPEN && trade.pnl !== undefined && (
        <div style={{ textAlign: "right", minWidth: 80 }}>
          <div
            className="num"
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: trade.pnl >= 0 ? "var(--green)" : "var(--red)",
            }}
          >
            {trade.pnl >= 0 ? "+" : ""}
            {trade.pnl.toFixed(2)}
          </div>
          {trade.pnl_percent !== undefined && (
            <div
              className="num"
              style={{
                fontSize: 10,
                color: trade.pnl_percent >= 0 ? "var(--green)" : "var(--red)",
              }}
            >
              {trade.pnl_percent >= 0 ? "+" : ""}
              {trade.pnl_percent.toFixed(2)}%
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, flexShrink: 0, alignItems: "flex-end" }}>
        <div style={{ display: "flex", gap: 6 }}>
          {trade.status === TradeStatus.INTENDED && (
            <button
              className="btn btn-primary"
              style={{ fontSize: 10, padding: "4px 10px" }}
              onClick={handleConfirm}
              disabled={loading}
            >
              CONFIRM
            </button>
          )}
          {(trade.status === TradeStatus.OPEN ||
            trade.status === TradeStatus.PENDING) && (
              <button
                className="btn btn-ghost"
                style={{
                  fontSize: 10,
                  padding: "4px 10px",
                  color: "var(--red)",
                  borderColor: "var(--red)",
                }}
                onClick={handleClose}
                disabled={loading}
              >
                CLOSE
              </button>
            )}
        </div>
        {error && (
          <span style={{ fontSize: 10, color: "var(--red)", maxWidth: 180, textAlign: "right" }}>
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
