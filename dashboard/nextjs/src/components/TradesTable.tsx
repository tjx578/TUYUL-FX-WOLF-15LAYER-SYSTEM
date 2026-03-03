"use client";

import { useMemo, useState } from "react";
import type { Trade } from "@/types";
import { confirmTrade, closeTrade } from "@/lib/api";

function formatTimestamp(ts?: string): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

function badgeColor(status: string): string {
  if (status === "INTENDED") return "rgba(0,245,160,0.14)";
  if (status === "PENDING") return "rgba(255,210,0,0.12)";
  if (status === "OPEN") return "rgba(0,160,255,0.12)";
  if (status === "CLOSED") return "rgba(255,255,255,0.06)";
  return "rgba(255,255,255,0.06)";
}

function badgeBorder(status: string): string {
  if (status === "INTENDED") return "rgba(0,245,160,0.28)";
  if (status === "PENDING") return "rgba(255,210,0,0.25)";
  if (status === "OPEN") return "rgba(0,160,255,0.22)";
  if (status === "CLOSED") return "rgba(255,255,255,0.10)";
  return "rgba(255,255,255,0.10)";
}

export default function TradesTable({
  trades,
  onAfterAction,
}: {
  trades: Trade[];
  onAfterAction?: () => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sorted = useMemo(() => {
    return [...trades].sort((a, b) => {
      const ta = new Date(a.updated_at ?? a.created_at).getTime();
      const tb = new Date(b.updated_at ?? b.created_at).getTime();
      return tb - ta;
    });
  }, [trades]);

  async function doConfirm(tradeId: string) {
    try {
      setError(null);
      setBusyId(tradeId);
      await confirmTrade(tradeId);
      onAfterAction?.();
    } catch (e: any) {
      setError(e?.message ?? "Confirm failed");
    } finally {
      setBusyId(null);
    }
  }

  async function doClose(tradeId: string) {
    try {
      setError(null);
      setBusyId(tradeId);
      await closeTrade(tradeId, "MANUAL_CLOSE");
      onAfterAction?.();
    } catch (e: any) {
      setError(e?.message ?? "Close failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {error && (
        <div
          style={{
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid rgba(255,60,60,0.28)",
            background: "rgba(255,60,60,0.10)",
            color: "var(--text-primary)",
            fontSize: 12,
          }}
        >
          {error}
        </div>
      )}

      <div
        style={{
          overflowX: "auto",
          borderRadius: 12,
          border: "1px solid rgba(255,255,255,0.08)",
          background: "var(--bg-card)",
        }}
      >
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              ["STATUS", "ACCOUNT", "PAIR", "DIR", "LOT", "ENTRY", "SL", "TP", "UPDATED", "ACTIONS"].map(
                (h) => (
                  <th
                    key={h}
                    style={{
                      padding: "12px 12px",
                      fontSize: 9,
                      letterSpacing: "0.12em",
                      color: "var(--text-muted)",
                      borderBottom: "1px solid rgba(255,255,255,0.08)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => {
              const isBusy = busyId === t.trade_id;
              const ts = t.updated_at ?? t.created_at;
              const canConfirm = t.status === "INTENDED";
              const canClose = t.status !== "CLOSED";
              return (
                <tr key={t.trade_id}>
                  <td style={{ padding: "10px 12px", whiteSpace: "nowrap" }}>
                    <span
                      style={{
                        fontSize: 10,
                        fontFamily: "var(--font-mono)",
                        padding: "4px 8px",
                        borderRadius: 999,
                        background: badgeColor(t.status),
                        border: `1px solid ${badgeBorder(t.status)}`,
                        color: "var(--text-primary)",
                      }}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <span className="num" style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {t.account_id}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <span className="num" style={{ fontWeight: 800 }}>
                      {t.pair}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px" }}>{t.direction}</td>
                  <td style={{ padding: "10px 12px" }}>
                    <span className="num">{Number(t.lot_size ?? 0).toFixed(2)}</span>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <span className="num">{Number(t.entry_price ?? 0).toFixed(5)}</span>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <span className="num">{Number(t.stop_loss ?? 0).toFixed(5)}</span>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <span className="num">{Number(t.take_profit ?? 0).toFixed(5)}</span>
                  </td>
                  <td style={{ padding: "10px 12px", whiteSpace: "nowrap" }}>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {formatTimestamp(ts)}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px", whiteSpace: "nowrap" }}>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        disabled={!canConfirm || isBusy}
                        onClick={() => doConfirm(t.trade_id)}
                        style={{
                          cursor: canConfirm && !isBusy ? "pointer" : "not-allowed",
                          padding: "7px 10px",
                          borderRadius: 10,
                          border: "1px solid rgba(0,245,160,0.25)",
                          background: "rgba(0,245,160,0.12)",
                          color: "var(--text-primary)",
                          fontSize: 10,
                          letterSpacing: "0.10em",
                          fontWeight: 800,
                          opacity: canConfirm ? 1 : 0.45,
                        }}
                      >
                        {isBusy && canConfirm ? "..." : "CONFIRM"}
                      </button>
                      <button
                        disabled={!canClose || isBusy}
                        onClick={() => doClose(t.trade_id)}
                        style={{
                          cursor: canClose && !isBusy ? "pointer" : "not-allowed",
                          padding: "7px 10px",
                          borderRadius: 10,
                          border: "1px solid rgba(255,60,60,0.25)",
                          background: "rgba(255,60,60,0.10)",
                          color: "var(--text-primary)",
                          fontSize: 10,
                          letterSpacing: "0.10em",
                          fontWeight: 800,
                          opacity: canClose ? 1 : 0.45,
                        }}
                      >
                        {isBusy && canClose ? "..." : "CLOSE"}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {sorted.length === 0 && (
              <tr>
                <td
                  colSpan={10}
                  style={{
                    padding: "18px 12px",
                    fontSize: 12,
                    color: "var(--text-muted)",
                    textAlign: "center",
                  }}
                >
                  No active trades. Waiting for TAKE…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}