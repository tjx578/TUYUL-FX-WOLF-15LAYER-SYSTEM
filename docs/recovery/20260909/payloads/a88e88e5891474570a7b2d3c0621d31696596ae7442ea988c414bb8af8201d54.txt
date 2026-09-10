"use client";

import type { Trade } from "@/types";
import { TradeStatusBadge, DirectionBadge, PnlCell } from "./TradeStatusBadge";
import type { MismatchFlag } from "@/hooks/useTradeDeskState";

interface TradeTableRowProps {
  trade: Trade;
  isSelected: boolean;
  onSelect: () => void;
  mismatchFlags: MismatchFlag[];
}

export function TradeTableRow({
  trade: t,
  isSelected,
  onSelect,
  mismatchFlags,
}: TradeTableRowProps) {
  const hasMismatch = mismatchFlags.some((f) => f.trade_id === t.trade_id);

  return (
    <tr
      onClick={onSelect}
      style={{
        cursor: "pointer",
        background: isSelected
          ? "rgba(26, 110, 255, 0.08)"
          : hasMismatch
          ? "rgba(255, 61, 87, 0.04)"
          : undefined,
        borderLeft: isSelected
          ? "2px solid var(--accent)"
          : hasMismatch
          ? "2px solid var(--red)"
          : "2px solid transparent",
        transition: "background 0.1s",
      }}
      aria-selected={isSelected}
    >
      {/* Trade ID */}
      <td>
        <span
          className="num"
          style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}
          title={t.trade_id}
        >
          {t.trade_id?.slice(0, 10)}…
          {hasMismatch && (
            <span
              title="Execution anomaly detected"
              style={{
                display: "inline-block",
                marginLeft: 5,
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "var(--red)",
                verticalAlign: "middle",
              }}
            />
          )}
        </span>
      </td>

      {/* Account */}
      <td>
        <span className="num" style={{ fontSize: 10, color: "var(--text-muted)" }}>
          {t.account_id?.slice(0, 8)}…
        </span>
      </td>

      {/* Pair */}
      <td>
        <span className="num" style={{ fontWeight: 700, color: "var(--text-primary)", fontSize: 12 }}>
          {t.pair ?? "—"}
        </span>
      </td>

      {/* Dir */}
      <td><DirectionBadge dir={t.direction} /></td>

      {/* Lot */}
      <td>
        <span className="num" style={{ color: "var(--text-secondary)", fontSize: 11 }}>
          {t.lot_size != null ? t.lot_size.toFixed(2) : "—"}
        </span>
      </td>

      {/* Entry */}
      <td className="num" style={{ fontSize: 11 }}>
        {t.entry_price != null ? t.entry_price.toFixed(5) : "—"}
      </td>

      {/* SL */}
      <td className="num" style={{ fontSize: 11, color: "var(--red)" }}>
        {t.stop_loss != null ? t.stop_loss.toFixed(5) : "—"}
      </td>

      {/* TP */}
      <td className="num" style={{ fontSize: 11, color: "var(--green)" }}>
        {t.take_profit != null ? t.take_profit.toFixed(5) : "—"}
      </td>

      {/* Risk% */}
      <td className="num" style={{ fontSize: 11 }}>
        {t.total_risk_percent != null ? `${t.total_risk_percent.toFixed(1)}%` : "—"}
      </td>

      {/* Status */}
      <td><TradeStatusBadge status={t.status} /></td>

      {/* PnL */}
      <td><PnlCell pnl={t.pnl} percent={t.pnl_percent} /></td>

      {/* Opened */}
      <td>
        <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
          {t.opened_at
            ? new Date(t.opened_at).toLocaleString("en-GB", {
                day: "2-digit", month: "short",
                hour: "2-digit", minute: "2-digit",
              })
            : "—"}
        </span>
      </td>
    </tr>
  );
}
