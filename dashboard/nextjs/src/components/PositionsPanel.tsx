"use client";

// ============================================================
// TUYUL FX — Positions Panel v8.1
// Source: PositionsPanel from Ultra Cockpit v8.0 (improved)
// Used in: Active Trades page
// Features: Open positions, Pending orders, P&L summary tabs
// ============================================================

import { useState } from "react";
import { T, RADIUS, FONT_MONO } from "@/lib/tokens";
import { M, L, Badge, Card, Tabs, Divider, KvGrid } from "@/components/ui";

// ── Types ─────────────────────────────────────────────────────
export interface Position {
  ticket: number;
  symbol: string;
  type: "BUY" | "SELL";
  lots: number;
  openPrice: number;
  sl: number;
  tp: number;
  profit: number;
  swap?: number;
  commission?: number;
  openTime: string;
}

export interface PendingOrder {
  ticket: number;
  symbol: string;
  type: "BUY_LIMIT" | "SELL_LIMIT" | "BUY_STOP" | "SELL_STOP";
  lots: number;
  price: number;
  sl: number;
  tp: number;
  openTime: string;
}

export interface PositionsPanelCallbacks {
  onPartialClose?: (ticket: number) => void;
  onMoveToBE?: (ticket: number) => void;
  onClose?: (ticket: number) => void;
  onModifyPending?: (ticket: number) => void;
  onDeletePending?: (ticket: number) => void;
}

interface Props extends PositionsPanelCallbacks {
  positions?: Position[];
  pendingOrders?: PendingOrder[];
}

// ── Mock data ─────────────────────────────────────────────────
export const MOCK_POSITIONS: Position[] = [
  {
    ticket: 10481,
    symbol: "EURUSD",
    type: "BUY",
    lots: 0.50,
    openPrice: 1.0842,
    sl: 1.0812,
    tp: 1.0902,
    profit: 42.00,
    swap: -1.20,
    commission: -3.50,
    openTime: "2026-02-24 09:15",
  },
  {
    ticket: 20193,
    symbol: "XAUUSD",
    type: "SELL",
    lots: 0.20,
    openPrice: 2652.40,
    sl: 2662.00,
    tp: 2632.00,
    profit: 189.00,
    swap: -2.10,
    commission: -4.00,
    openTime: "2026-02-24 07:30",
  },
];

export const MOCK_PENDING: PendingOrder[] = [
  {
    ticket: 20194,
    symbol: "GBPUSD",
    type: "BUY_LIMIT",
    lots: 0.30,
    price: 1.2680,
    sl: 1.2650,
    tp: 1.2740,
    openTime: "2026-02-24 10:00",
  },
];

// ── Helpers ───────────────────────────────────────────────────
function pColor(type: "BUY" | "SELL"): string {
  return type === "BUY" ? T.emerald : T.red;
}

function netPnl(p: Position): number {
  return p.profit + (p.swap ?? 0) + (p.commission ?? 0);
}

// ── Sub-component: Empty state ────────────────────────────────
function Empty({ message }: { message: string }) {
  return (
    <div style={{
      textAlign: "center",
      padding: 18,
      color: T.t4,
      fontSize: 10,
      fontFamily: FONT_MONO,
    }}>
      {message}
    </div>
  );
}

// ── Sub-component: Action button ─────────────────────────────
function ActionBtn({
  label, danger = false, onClick,
}: {
  label: string; danger?: boolean; onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="btn-action"
      style={{
        padding: "3px 7px",
        borderRadius: RADIUS.xs,
        border: `1px solid ${danger ? `${T.red}30` : T.b1}`,
        backgroundColor: "transparent",
        color: danger ? T.red : T.t3,
        fontSize: 8,
        cursor: "pointer",
        fontFamily: FONT_MONO,
      }}
    >
      {label}
    </button>
  );
}

// ── Sub-component: Open position card ────────────────────────
function PositionRow({
  p, onPartialClose, onMoveToBE, onClose,
}: {
  p: Position;
  onPartialClose?: (ticket: number) => void;
  onMoveToBE?: (ticket: number) => void;
  onClose?: (ticket: number) => void;
}) {
  const typeColor = pColor(p.type);

  return (
    <div style={{
      padding: "9px 10px",
      backgroundColor: T.bg1,
      borderRadius: RADIUS.sm,
      marginBottom: 5,
      border: `1px solid ${typeColor}18`,
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 6,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <Badge color={typeColor}>
            {p.type === "BUY" ? "▲" : "▼"} {p.type}
          </Badge>
          <M s={12} w={700}>{p.symbol}</M>
          <M s={9} c={T.t4}>#{p.ticket}</M>
        </div>
        <M s={13} w={700} c={p.profit >= 0 ? T.emerald : T.red}>
          {p.profit >= 0 ? "+" : ""}{p.profit.toFixed(2)}
        </M>
      </div>

      {/* Details grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 5 }}>
        {([
          { l: "Lots",  v: p.lots.toFixed(2),        c: T.t2     },
          { l: "Entry", v: p.openPrice,               c: T.t2     },
          { l: "SL",    v: p.sl,                      c: T.red    },
          { l: "TP",    v: p.tp,                      c: T.emerald },
          { l: "Swap",  v: (p.swap ?? 0).toFixed(2),  c: T.amber  },
        ] as { l: string; v: React.ReactNode; c: string }[]).map((item, i) => (
          <div key={i}>
            <L s={7} c={T.t4}>{item.l}</L>
            <div><M s={9} c={item.c}>{item.v}</M></div>
          </div>
        ))}
      </div>

      {/* Open time */}
      <div style={{ marginTop: 5 }}>
        <M s={8} c={T.t4}>{p.openTime}</M>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: 4, marginTop: 7 }}>
        <ActionBtn label="Partial Close" onClick={() => onPartialClose?.(p.ticket)} />
        <ActionBtn label="Move SL→BE"   onClick={() => onMoveToBE?.(p.ticket)} />
        <ActionBtn label="Close"         onClick={() => onClose?.(p.ticket)} danger />
      </div>
    </div>
  );
}

// ── Sub-component: Pending order card ────────────────────────
function PendingRow({
  p, onModify, onDelete,
}: {
  p: PendingOrder;
  onModify?: (ticket: number) => void;
  onDelete?: (ticket: number) => void;
}) {
  return (
    <div style={{
      padding: "9px 10px",
      backgroundColor: T.bg1,
      borderRadius: RADIUS.sm,
      marginBottom: 5,
      border: `1px solid ${T.amber}18`,
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 6,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <Badge color={T.amber}>{p.type.replace("_", " ")}</Badge>
          <M s={12} w={700}>{p.symbol}</M>
          <M s={9} c={T.t4}>#{p.ticket}</M>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          <ActionBtn label="Modify" onClick={() => onModify?.(p.ticket)} />
          <ActionBtn label="Delete" onClick={() => onDelete?.(p.ticket)} danger />
        </div>
      </div>

      {/* Details */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 5 }}>
        {([
          { l: "Price", v: p.price, c: T.t2     },
          { l: "Lots",  v: p.lots,  c: T.t2     },
          { l: "SL",    v: p.sl,    c: T.red     },
          { l: "TP",    v: p.tp,    c: T.emerald },
        ] as { l: string; v: React.ReactNode; c: string }[]).map((item, i) => (
          <div key={i}>
            <L s={7} c={T.t4}>{item.l}</L>
            <div><M s={9} c={item.c}>{item.v}</M></div>
          </div>
        ))}
      </div>

      {/* Placed time */}
      <div style={{ marginTop: 5 }}>
        <M s={8} c={T.t4}>{p.openTime}</M>
      </div>
    </div>
  );
}

// ── Sub-component: P&L summary tab ───────────────────────────
function PnLSummary({ positions }: { positions: Position[] }) {
  const totalProfit = positions.reduce((s, p) => s + p.profit, 0);
  const totalSwap   = positions.reduce((s, p) => s + (p.swap ?? 0), 0);
  const totalComm   = positions.reduce((s, p) => s + (p.commission ?? 0), 0);
  const net         = totalProfit + totalSwap + totalComm;

  return (
    <div>
      {/* Aggregate row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 10 }}>
        {([
          { l: "Gross Profit", v: `$${totalProfit.toFixed(2)}`, c: totalProfit >= 0 ? T.emerald : T.red },
          { l: "Total Swap",   v: `$${totalSwap.toFixed(2)}`,   c: T.amber },
          { l: "Commission",   v: `$${totalComm.toFixed(2)}`,   c: T.t2   },
          { l: "Net P&L",      v: `$${net.toFixed(2)}`,         c: net >= 0 ? T.emerald : T.red },
        ] as { l: string; v: string; c: string }[]).map((item, i) => (
          <div key={i} style={{
            padding: "8px 10px",
            borderRadius: RADIUS.sm,
            backgroundColor: T.bg1,
            border: `1px solid ${T.b0}`,
          }}>
            <L s={7} c={T.t4}>{item.l}</L>
            <div><M s={13} w={700} c={item.c}>{item.v}</M></div>
          </div>
        ))}
      </div>

      <Divider my={4} />

      {/* Per-position breakdown */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {positions.map((p) => (
          <div key={p.ticket} style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "6px 8px",
            borderRadius: RADIUS.xs,
            backgroundColor: T.bg1,
            border: `1px solid ${T.b0}`,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <M s={9} w={700} c={pColor(p.type)}>{p.type === "BUY" ? "▲" : "▼"}</M>
              <M s={10} w={700}>{p.symbol}</M>
              <M s={9} c={T.t4}>#{p.ticket}</M>
            </div>
            <KvGrid
              cols={2}
              rows={[
                { label: "Gross", value: `$${p.profit.toFixed(2)}`,        color: p.profit >= 0 ? T.emerald : T.red },
                { label: "Net",   value: `$${netPnl(p).toFixed(2)}`,       color: netPnl(p) >= 0 ? T.emerald : T.red },
              ]}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ── PositionsPanel ────────────────────────────────────────────
export function PositionsPanel({
  positions = MOCK_POSITIONS,
  pendingOrders = MOCK_PENDING,
  onPartialClose,
  onMoveToBE,
  onClose,
  onModifyPending,
  onDeletePending,
}: Props) {
  const [tab, setTab] = useState<"positions" | "pending" | "summary">("positions");

  const totalProfit = positions.reduce((s, p) => s + p.profit, 0);

  return (
    <Card
      title="POSITIONS"
      sub={`${positions.length} open · ${pendingOrders.length} pending`}
      icon="▦"
      accentColor={totalProfit >= 0 ? "ok" : "danger"}
    >
      <Tabs
        compact
        tabs={[
          { id: "positions", label: "Open",    icon: "▦" },
          { id: "pending",   label: "Pending", icon: "◷" },
          { id: "summary",   label: "P&L",     icon: "$" },
        ]}
        active={tab}
        onChange={(id) => setTab(id as typeof tab)}
      />

      {/* ── Open Positions ── */}
      {tab === "positions" && (
        positions.length === 0
          ? <Empty message="— no open positions —" />
          : positions.map((p) => (
              <PositionRow
                key={p.ticket}
                p={p}
                onPartialClose={onPartialClose}
                onMoveToBE={onMoveToBE}
                onClose={onClose}
              />
            ))
      )}

      {/* ── Pending Orders ── */}
      {tab === "pending" && (
        pendingOrders.length === 0
          ? <Empty message="— no pending orders —" />
          : pendingOrders.map((p) => (
              <PendingRow
                key={p.ticket}
                p={p}
                onModify={onModifyPending}
                onDelete={onDeletePending}
              />
            ))
      )}

      {/* ── P&L Summary ── */}
      {tab === "summary" && <PnLSummary positions={positions} />}
    </Card>
  );
}

export default PositionsPanel;
