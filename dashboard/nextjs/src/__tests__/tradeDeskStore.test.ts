/**
 * Unit tests for Trade Desk store, helpers, and state management.
 *
 * Tests:
 *  - Trade state partitioning (pending/open/closed/cancelled)
 *  - Anomaly detection in store
 *  - Exposure aggregation types
 *  - Store snapshot application preserves selected trade
 *  - Execution mismatch flags
 *  - Trade patching + removal
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useTradeDeskStore } from "@/store/useTradeDeskStore";
import type { TradeDeskTrade, TradeDeskResponse, ExposureSummary } from "@/features/trades/model/tradeDeskSchema";

// ── Test data factories ──────────────────────────────────────

function makeTrade(overrides: Partial<TradeDeskTrade> = {}): TradeDeskTrade {
  return {
    trade_id: "T-001",
    signal_id: undefined,
    account_id: "ACC-001",
    status: "OPEN",
    pair: "EURUSD",
    direction: "BUY",
    lot_size: 0.1,
    entry_price: 1.1,
    stop_loss: 1.095,
    take_profit: 1.11,
    pnl: undefined,
    opened_at: undefined,
    closed_at: undefined,
    created_at: undefined,
    confirmed_at: undefined,
    close_reason: undefined,
    current_price: undefined,
    total_risk_percent: undefined,
    total_risk_amount: undefined,
    ...overrides,
  };
}

function makeDeskResponse(overrides: Partial<TradeDeskResponse> = {}): TradeDeskResponse {
  return {
    trades: {
      pending: [],
      open: [],
      closed: [],
      cancelled: [],
    },
    exposure: {
      by_pair: [],
      by_account: [],
      total_lots: 0,
      total_trades: 0,
    },
    anomalies: [],
    counts: { pending: 0, open: 0, closed: 0, cancelled: 0, total: 0 },
    server_ts: Date.now() / 1000,
    ...overrides,
  };
}

// ── Reset store before each test ─────────────────────────────

beforeEach(() => {
  const store = useTradeDeskStore.getState();
  useTradeDeskStore.setState({
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
  });
});

// ══════════════════════════════════════════════════════════════
//  Trade State Partitioning
// ══════════════════════════════════════════════════════════════

describe("Trade state partitioning", () => {
  it("should partition trades into correct tabs on snapshot", () => {
    const response = makeDeskResponse({
      trades: {
        pending: [makeTrade({ trade_id: "T-1", status: "PENDING" })],
        open: [
          makeTrade({ trade_id: "T-2", status: "OPEN" }),
          makeTrade({ trade_id: "T-3", status: "OPEN" }),
        ],
        closed: [makeTrade({ trade_id: "T-4", status: "CLOSED" })],
        cancelled: [makeTrade({ trade_id: "T-5", status: "CANCELLED" })],
      },
      counts: { pending: 1, open: 2, closed: 1, cancelled: 1, total: 5 },
    });

    useTradeDeskStore.getState().applyDeskSnapshot(response);
    const state = useTradeDeskStore.getState();

    expect(state.pendingTrades).toHaveLength(1);
    expect(state.openTrades).toHaveLength(2);
    expect(state.closedTrades).toHaveLength(1);
    expect(state.cancelledTrades).toHaveLength(1);
    expect(state.counts?.total).toBe(5);
  });

  it("should handle empty response gracefully", () => {
    const response = makeDeskResponse();
    useTradeDeskStore.getState().applyDeskSnapshot(response);
    const state = useTradeDeskStore.getState();

    expect(state.pendingTrades).toHaveLength(0);
    expect(state.openTrades).toHaveLength(0);
    expect(state.counts?.total).toBe(0);
  });
});

// ══════════════════════════════════════════════════════════════
//  Selected Trade Preservation
// ══════════════════════════════════════════════════════════════

describe("Selected trade preservation on delta", () => {
  it("should preserve selectedTradeId when trade still exists in snapshot", () => {
    // Pre-set selection
    useTradeDeskStore.setState({ selectedTradeId: "T-2" });

    const response = makeDeskResponse({
      trades: {
        pending: [],
        open: [makeTrade({ trade_id: "T-2", status: "OPEN" })],
        closed: [],
        cancelled: [],
      },
      counts: { pending: 0, open: 1, closed: 0, cancelled: 0, total: 1 },
    });

    useTradeDeskStore.getState().applyDeskSnapshot(response);
    expect(useTradeDeskStore.getState().selectedTradeId).toBe("T-2");
  });

  it("should clear selectedTradeId when trade no longer exists in snapshot", () => {
    useTradeDeskStore.setState({ selectedTradeId: "T-GONE" });

    const response = makeDeskResponse({
      trades: { pending: [], open: [], closed: [], cancelled: [] },
      counts: { pending: 0, open: 0, closed: 0, cancelled: 0, total: 0 },
    });

    useTradeDeskStore.getState().applyDeskSnapshot(response);
    // Phase 2 fix: selection is cleared when the trade disappears from all lists
    expect(useTradeDeskStore.getState().selectedTradeId).toBeNull();
  });
});

// ══════════════════════════════════════════════════════════════
//  Trade Patching
// ══════════════════════════════════════════════════════════════

describe("Trade patching", () => {
  it("should update an existing trade in the correct tab", () => {
    const initial = makeTrade({ trade_id: "T-1", status: "OPEN", pnl: 10 });
    useTradeDeskStore.setState({ openTrades: [initial] });

    const updated = makeTrade({ trade_id: "T-1", status: "OPEN", pnl: 25 });
    useTradeDeskStore.getState().patchTrade(updated);

    const state = useTradeDeskStore.getState();
    expect(state.openTrades[0].pnl).toBe(25);
  });

  it("should not add trade if not already in the list", () => {
    useTradeDeskStore.setState({ openTrades: [] });

    const newTrade = makeTrade({ trade_id: "T-NEW", status: "OPEN" });
    useTradeDeskStore.getState().patchTrade(newTrade);

    expect(useTradeDeskStore.getState().openTrades).toHaveLength(0);
  });
});

// ══════════════════════════════════════════════════════════════
//  Trade Removal
// ══════════════════════════════════════════════════════════════

describe("Trade removal", () => {
  it("should remove trade from active list", () => {
    const trade = makeTrade({ trade_id: "T-1", status: "OPEN" });
    useTradeDeskStore.setState({ openTrades: [trade] });

    useTradeDeskStore.getState().removeTrade("T-1");
    expect(useTradeDeskStore.getState().openTrades).toHaveLength(0);
  });

  it("should clear selectedTradeId when removed trade is selected", () => {
    useTradeDeskStore.setState({
      selectedTradeId: "T-1",
      openTrades: [makeTrade({ trade_id: "T-1" })],
    });

    useTradeDeskStore.getState().removeTrade("T-1");
    expect(useTradeDeskStore.getState().selectedTradeId).toBeNull();
  });

  it("should not clear selectedTradeId when another trade is removed", () => {
    useTradeDeskStore.setState({
      selectedTradeId: "T-1",
      openTrades: [
        makeTrade({ trade_id: "T-1" }),
        makeTrade({ trade_id: "T-2" }),
      ],
    });

    useTradeDeskStore.getState().removeTrade("T-2");
    expect(useTradeDeskStore.getState().selectedTradeId).toBe("T-1");
  });
});

// ══════════════════════════════════════════════════════════════
//  Execution Mismatch Flags
// ══════════════════════════════════════════════════════════════

describe("Execution mismatch flags", () => {
  it("should set mismatch flags for a trade", () => {
    useTradeDeskStore.getState().setExecutionMismatch("T-1", ["PRICE_STALE", "LOT_DIFF"]);

    const flags = useTradeDeskStore.getState().executionMismatchFlags;
    expect(flags["T-1"]).toEqual(["PRICE_STALE", "LOT_DIFF"]);
  });

  it("should clear mismatch flags for a trade", () => {
    useTradeDeskStore.getState().setExecutionMismatch("T-1", ["SYNC"]);
    useTradeDeskStore.getState().clearExecutionMismatch("T-1");

    expect(useTradeDeskStore.getState().executionMismatchFlags["T-1"]).toBeUndefined();
  });

  it("should not affect other trade flags when clearing one", () => {
    useTradeDeskStore.getState().setExecutionMismatch("T-1", ["A"]);
    useTradeDeskStore.getState().setExecutionMismatch("T-2", ["B"]);
    useTradeDeskStore.getState().clearExecutionMismatch("T-1");

    const flags = useTradeDeskStore.getState().executionMismatchFlags;
    expect(flags["T-1"]).toBeUndefined();
    expect(flags["T-2"]).toEqual(["B"]);
  });
});

// ══════════════════════════════════════════════════════════════
//  Tab switching
// ══════════════════════════════════════════════════════════════

describe("Tab switching", () => {
  it("should change active tab", () => {
    useTradeDeskStore.getState().setActiveTab("pending");
    expect(useTradeDeskStore.getState().activeTab).toBe("pending");

    useTradeDeskStore.getState().setActiveTab("closed");
    expect(useTradeDeskStore.getState().activeTab).toBe("closed");
  });
});

// ══════════════════════════════════════════════════════════════
//  Exposure aggregation types
// ══════════════════════════════════════════════════════════════

describe("Exposure summary structure", () => {
  it("should accept valid exposure data", () => {
    const exposure: ExposureSummary = {
      by_pair: [{ pair: "EURUSD", total_lots: 0.2, buy_lots: 0.1, sell_lots: 0.1, count: 2 }],
      by_account: [{ account_id: "ACC-1", total_lots: 0.2, count: 2, pairs: ["EURUSD"] }],
      total_lots: 0.2,
      total_trades: 2,
    };

    useTradeDeskStore.setState({ exposure });
    expect(useTradeDeskStore.getState().exposure?.total_lots).toBe(0.2);
  });
});
