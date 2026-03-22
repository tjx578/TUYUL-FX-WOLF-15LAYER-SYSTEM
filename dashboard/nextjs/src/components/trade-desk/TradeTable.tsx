"use client";

import React, { useCallback } from "react";
import type { TradeDeskTrade } from "@/schema/tradeDeskSchema";
import { TradeStatusBadge, SyncMismatchIndicator } from "./TradeStatusBadge";
import { formatDate } from "@/lib/formatters";

// ── DirectionBadge ───────────────────────────────────────────

function DirectionBadge({ dir }: { dir?: string }) {
    if (!dir) return <span style={{ color: "var(--text-muted)" }}>—</span>;
    return (
        <span
            className="badge num"
            style={{
                background: dir === "BUY" ? "var(--green-glow)" : "var(--red-glow)",
                color: dir === "BUY" ? "var(--green)" : "var(--red)",
                border: `1px solid ${dir === "BUY" ? "var(--border-success)" : "var(--border-danger)"}`,
                fontSize: 10,
                fontWeight: 800,
            }}
        >
            {dir}
        </span>
    );
}

// ── PnlCell ──────────────────────────────────────────────────

function PnlCell({ pnl }: { pnl?: number }) {
    if (pnl === undefined || pnl === null) return <span style={{ color: "var(--text-muted)" }}>—</span>;
    const color = pnl >= 0 ? "var(--green)" : "var(--red)";
    return (
        <span className="num" style={{ color, fontWeight: 700 }}>
            {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}
        </span>
    );
}

// ── TradeTableRow ────────────────────────────────────────────

interface TradeTableRowProps {
    trade: TradeDeskTrade;
    isSelected: boolean;
    onSelect: (id: string) => void;
    mismatchFlags?: string[];
}

export const TradeTableRow = React.memo(
    function TradeTableRow({ trade, isSelected, onSelect, mismatchFlags }: TradeTableRowProps) {
        const pair = trade.pair ?? "—";
        const dir = trade.direction;
        const lot = trade.lot_size;

        return (
            <tr
                data-testid={`trade-row-${trade.trade_id}`}
                role="button"
                tabIndex={0}
                aria-label={`Trade ${pair} ${dir ?? ""} — ${trade.status}`}
                onClick={() => onSelect(trade.trade_id)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(trade.trade_id); } }}
                style={{
                    cursor: "pointer",
                    borderBottom: "1px solid var(--border-subtle, rgba(255,255,255,0.06))",
                    background: isSelected ? "var(--bg-selected, rgba(56,189,248,0.06))" : undefined,
                }}
            >
                <td style={{ padding: "8px 10px" }}>
                    <span className="num" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                        {trade.trade_id?.slice(0, 12)}…
                    </span>
                </td>
                <td>
                    <span className="num" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                        {trade.account_id?.slice(0, 10)}…
                    </span>
                </td>
                <td>
                    <span className="num" style={{ fontWeight: 700, color: "var(--text-primary)" }}>{pair}</span>
                </td>
                <td><DirectionBadge dir={dir} /></td>
                <td>
                    <span className="num" style={{ color: "var(--text-secondary)" }}>
                        {lot != null ? lot.toFixed(2) : "—"}
                    </span>
                </td>
                <td className="num" style={{ fontSize: 11 }}>
                    {trade.entry_price != null ? trade.entry_price.toFixed(5) : "—"}
                </td>
                <td className="num" style={{ fontSize: 11, color: "var(--red)" }}>
                    {trade.stop_loss != null ? trade.stop_loss.toFixed(5) : "—"}
                </td>
                <td className="num" style={{ fontSize: 11, color: "var(--green)" }}>
                    {trade.take_profit != null ? trade.take_profit.toFixed(5) : "—"}
                </td>
                <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <TradeStatusBadge status={trade.status} />
                        {mismatchFlags && mismatchFlags.length > 0 && (
                            <SyncMismatchIndicator flags={mismatchFlags} />
                        )}
                    </div>
                </td>
                <td><PnlCell pnl={trade.pnl} /></td>
                <td>
                    <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                        {trade.opened_at
                            ? formatDate(trade.opened_at)
                            : trade.created_at
                                ? formatDate(trade.created_at)
                                : "—"}
                    </span>
                </td>
            </tr>
        );
    },
    (prev, next) =>
        prev.trade.trade_id === next.trade.trade_id &&
        prev.trade.pnl === next.trade.pnl &&
        prev.trade.status === next.trade.status &&
        prev.isSelected === next.isSelected &&
        prev.onSelect === next.onSelect &&
        prev.mismatchFlags === next.mismatchFlags,
);

// ── TradeTable ───────────────────────────────────────────────

const HEADERS = ["TRADE ID", "ACCOUNT", "PAIR", "DIR", "LOT", "ENTRY", "SL", "TP", "STATUS", "PNL", "TIME"];

interface TradeTableProps {
    trades: TradeDeskTrade[];
    selectedTradeId: string | null;
    onSelectTrade: (id: string) => void;
    executionMismatchFlags?: Record<string, string[]>;
    emptyMessage?: string;
}

export function TradeTable({
    trades,
    selectedTradeId,
    onSelectTrade,
    executionMismatchFlags = {},
    emptyMessage = "No trades in this tab.",
}: TradeTableProps) {
    // stable reference so memoized rows don't re-render on every parent render
    const handleSelect = useCallback((id: string) => onSelectTrade(id), [onSelectTrade]);

    if (trades.length === 0) {
        return (
            <div
                className="panel"
                style={{ padding: "32px 20px", textAlign: "center", fontSize: 12, color: "var(--text-muted)" }}
            >
                {emptyMessage}
            </div>
        );
    }

    return (
        <div
            style={{
                overflowX: "auto",
                borderRadius: "var(--radius-lg)",
                border: "1px solid var(--border-default)",
            }}
            role="region"
            aria-label="Trades table"
        >
            <table>
                <thead>
                    <tr>
                        {HEADERS.map((h) => (
                            <th key={h}>{h}</th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {trades.map((t) => (
                        <TradeTableRow
                            key={t.trade_id}
                            trade={t}
                            isSelected={selectedTradeId === t.trade_id}
                            onSelect={handleSelect}
                            mismatchFlags={executionMismatchFlags[t.trade_id]}
                        />
                    ))}
                </tbody>
            </table>
        </div>
    );
}
