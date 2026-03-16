"use client";

// ============================================================
// TUYUL FX Wolf-15 — Trade Desk Page (/trades) — P0 rewrite
// Tabs: pending / open / closed / cancelled
// Detail panel + execution timeline + anomaly markers
// Exposure aggregation by pair/account
// Sync mismatch indicator
// ============================================================

import { useMemo } from "react";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import {
  TradeTabs,
  TradeTable,
  TradeDetailPanel,
  TradeActionPanel,
  ExposureSummaryPanel,
  ExecutionAnomalyBanner,
} from "@/components/trade-desk";
import { useTradeDeskState, useTradeDeskLivePrices } from "@/hooks/useTradeDeskHooks";
import type { TradeDeskTrade } from "@/schema/tradeDeskSchema";

// ── KPI summary ───────────────────────────────────────────────

function TradeKpi({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="card" style={{ padding: "11px 14px", display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--text-muted)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
        {label}
      </div>
      <div className="num" style={{ fontSize: 20, fontWeight: 700, color: color ?? "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────

export default function TradeDeskPage() {
  const {
    activeTab,
    setActiveTab,
    pendingTrades,
    openTrades,
    closedTrades,
    cancelledTrades,
    selectedTradeId,
    setSelectedTradeId,
    exposure,
    anomalies,
    counts,
    executionMismatchFlags,
  } = useTradeDeskState();

  // Live prices (ref-based, no re-render per tick)
  useTradeDeskLivePrices();

  // Current tab trades
  const currentTrades: TradeDeskTrade[] = useMemo(() => {
    switch (activeTab) {
      case "pending": return pendingTrades;
      case "open": return openTrades;
      case "closed": return closedTrades;
      case "cancelled": return cancelledTrades;
      default: return openTrades;
    }
  }, [activeTab, pendingTrades, openTrades, closedTrades, cancelledTrades]);

  // Selected trade from any list
  const selectedTrade = useMemo(() => {
    if (!selectedTradeId) return null;
    const all = [...pendingTrades, ...openTrades, ...closedTrades, ...cancelledTrades];
    return all.find((t) => t.trade_id === selectedTradeId) ?? null;
  }, [selectedTradeId, pendingTrades, openTrades, closedTrades, cancelledTrades]);

  // Stats
  const activeCount = (counts?.pending ?? 0) + (counts?.open ?? 0);
  const totalPnl = useMemo(() => {
    return [...openTrades, ...closedTrades].reduce((sum, t) => sum + (t.pnl ?? 0), 0);
  }, [openTrades, closedTrades]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="trades" />

      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 800,
              letterSpacing: "0.06em",
              color: "var(--text-primary)",
              margin: 0,
              fontFamily: "var(--font-display)",
            }}
          >
            TRADE DESK
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            Full lifecycle — INTENDED → PENDING → OPEN → CLOSED
          </p>
        </div>
      </div>

      {/* ── Anomaly Banner ── */}
      <ExecutionAnomalyBanner anomalies={anomalies} />

      {/* ── KPI row ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12 }}>
        <TradeKpi
          label="ACTIVE NOW"
          value={activeCount}
          color={activeCount > 0 ? "var(--green)" : "var(--text-muted)"}
        />
        <TradeKpi
          label="OPEN"
          value={counts?.open ?? 0}
          color={(counts?.open ?? 0) > 0 ? "var(--blue)" : "var(--text-muted)"}
        />
        <TradeKpi label="CLOSED" value={counts?.closed ?? 0} color="var(--text-secondary)" />
        <TradeKpi
          label="TOTAL PNL"
          value={`${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}`}
          color={totalPnl >= 0 ? "var(--green)" : "var(--red)"}
        />
      </div>

      {/* ── Tabs ── */}
      <TradeTabs activeTab={activeTab} onTabChange={setActiveTab} counts={counts} />

      {/* ── Main content: table + detail panel ── */}
      <div style={{ display: "grid", gridTemplateColumns: selectedTradeId ? "1fr 360px" : "1fr", gap: 16 }}>
        {/* Trade table */}
        <TradeTable
          trades={currentTrades}
          selectedTradeId={selectedTradeId}
          onSelectTrade={setSelectedTradeId}
          executionMismatchFlags={executionMismatchFlags}
          emptyMessage={`No ${activeTab} trades.`}
        />

        {/* Detail panel (shown when a trade is selected) */}
        {selectedTradeId && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <TradeDetailPanel
              tradeId={selectedTradeId}
              onClose={() => setSelectedTradeId(null)}
            />
            {selectedTrade && (
              <TradeActionPanel trade={selectedTrade} />
            )}
          </div>
        )}
      </div>

      {/* ── Exposure Summary ── */}
      <ExposureSummaryPanel exposure={exposure} />
    </div>
  );
}
