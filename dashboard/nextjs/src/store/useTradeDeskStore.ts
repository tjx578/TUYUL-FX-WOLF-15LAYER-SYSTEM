"use client";

import { create } from "zustand";
import type {
  TradeDeskTrade,
  TradeDeskResponse,
  ExposureSummary,
  TradeAnomaly,
  TradeDeskCounts,
} from "@/schema/tradeDeskSchema";

// ── Types ────────────────────────────────────────────────────

export type TradeTab = "pending" | "open" | "closed" | "cancelled";

interface TradeDeskState {
  // Tab data
  activeTab: TradeTab;
  pendingTrades: TradeDeskTrade[];
  openTrades: TradeDeskTrade[];
  closedTrades: TradeDeskTrade[];
  cancelledTrades: TradeDeskTrade[];

  // Selection
  selectedTradeId: string | null;

  // Exposure & anomalies
  exposure: ExposureSummary | null;
  anomalies: TradeAnomaly[];
  counts: TradeDeskCounts | null;
  serverTs: number | null;

  // Execution mismatch flags
  executionMismatchFlags: Record<string, string[]>;

  // Actions
  setActiveTab: (tab: TradeTab) => void;
  setSelectedTradeId: (id: string | null) => void;
  applyDeskSnapshot: (data: TradeDeskResponse) => void;
  patchTrade: (trade: TradeDeskTrade) => void;
  removeTrade: (tradeId: string) => void;
  setExecutionMismatch: (tradeId: string, flags: string[]) => void;
  clearExecutionMismatch: (tradeId: string) => void;
}

// ── Helpers ──────────────────────────────────────────────────

function patchTradeInList(
  list: TradeDeskTrade[],
  trade: TradeDeskTrade
): TradeDeskTrade[] {
  const idx = list.findIndex((t) => t.trade_id === trade.trade_id);
  if (idx === -1) return list;
  const next = [...list];
  next[idx] = trade;
  return next;
}

function removeTradeFromList(
  list: TradeDeskTrade[],
  tradeId: string
): TradeDeskTrade[] {
  return list.filter((t) => t.trade_id !== tradeId);
}

// ── Store ────────────────────────────────────────────────────

export const useTradeDeskStore = create<TradeDeskState>((set) => ({
  activeTab: "open",
  pendingTrades: [],
  openTrades: [],
  closedTrades: [],
  cancelledTrades: [],
  selectedTradeId: null,
  exposure: null,
  anomalies: [],
  counts: null,
  serverTs: null,
  executionMismatchFlags: {},

  setActiveTab: (tab) => set({ activeTab: tab }),

  setSelectedTradeId: (id) => set({ selectedTradeId: id }),

  applyDeskSnapshot: (data) =>
    set((state) => {
      // Preserve selectedTradeId if the trade still exists in any list
      const allTrades = [
        ...data.trades.pending,
        ...data.trades.open,
        ...data.trades.closed,
        ...data.trades.cancelled,
      ];
      const selectedStillExists = state.selectedTradeId
        ? allTrades.some((t) => t.trade_id === state.selectedTradeId)
        : false;

      return {
        pendingTrades: data.trades.pending,
        openTrades: data.trades.open,
        closedTrades: data.trades.closed,
        cancelledTrades: data.trades.cancelled,
        exposure: data.exposure,
        anomalies: data.anomalies,
        counts: data.counts,
        serverTs: data.server_ts,
        // Clear selection if trade no longer exists in any list
        selectedTradeId: selectedStillExists ? state.selectedTradeId : null,
      };
    }),

  patchTrade: (trade) =>
    set((state) => ({
      pendingTrades: patchTradeInList(state.pendingTrades, trade),
      openTrades: patchTradeInList(state.openTrades, trade),
      closedTrades: patchTradeInList(state.closedTrades, trade),
      cancelledTrades: patchTradeInList(state.cancelledTrades, trade),
    })),

  removeTrade: (tradeId) =>
    set((state) => ({
      pendingTrades: removeTradeFromList(state.pendingTrades, tradeId),
      openTrades: removeTradeFromList(state.openTrades, tradeId),
      closedTrades: removeTradeFromList(state.closedTrades, tradeId),
      cancelledTrades: removeTradeFromList(state.cancelledTrades, tradeId),
      selectedTradeId:
        state.selectedTradeId === tradeId ? null : state.selectedTradeId,
    })),

  setExecutionMismatch: (tradeId, flags) =>
    set((state) => ({
      executionMismatchFlags: {
        ...state.executionMismatchFlags,
        [tradeId]: flags,
      },
    })),

  clearExecutionMismatch: (tradeId) =>
    set((state) => {
      const next = { ...state.executionMismatchFlags };
      delete next[tradeId];
      return { executionMismatchFlags: next };
    }),
}));
