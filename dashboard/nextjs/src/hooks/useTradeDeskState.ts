"use client";

// ============================================================
// useTradeDeskState — Trade Desk P0 orchestration hook
// Bootstrap: REST (useActiveTrades + useTradesQuery)
// Live:      useLiveTrades WS delta merge
// Derived:   pendingTrades, openTrades, closedTrades,
//            selectedTrade (WS-stable), executionMismatchFlags,
//            exposureByPair, exposureByAccount
// Mutations: confirmTrade, closeTrade
// ============================================================

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useActiveTrades, useAccounts, confirmTrade, closeTrade } from "@/lib/api";
import { useLiveTrades } from "@/lib/realtime/hooks/useLiveTrades";
import { useTradesQuery } from "@/hooks/queries/useTradesQuery";
import { useTableQueryStore } from "@/store/useTableQueryStore";
import type { Trade, Account } from "@/types";
import { TradeStatus, CloseReason } from "@/types";

// ─── Anomaly detection ───────────────────────────────────────

export interface MismatchFlag {
  trade_id: string;
  type: "ENTRY_DRIFT" | "LOT_MISMATCH" | "ORPHANED" | "DOUBLE_COUNTED";
  message: string;
}

function detectMismatches(trades: Trade[]): MismatchFlag[] {
  const flags: MismatchFlag[] = [];
  const seen = new Map<string, number>();

  for (const t of trades) {
    // Duplicate trade_id
    const prev = seen.get(t.trade_id);
    if (prev !== undefined) {
      flags.push({
        trade_id: t.trade_id,
        type: "DOUBLE_COUNTED",
        message: `Trade ${t.trade_id.slice(0, 8)} appears more than once`,
      });
    }
    seen.set(t.trade_id, (prev ?? 0) + 1);

    // Entry drift: entry_price missing on OPEN trade
    if (t.status === TradeStatus.OPEN && !t.entry_price) {
      flags.push({
        trade_id: t.trade_id,
        type: "ENTRY_DRIFT",
        message: `Trade ${t.trade_id.slice(0, 8)} is OPEN but has no entry_price`,
      });
    }

    // Orphaned: PENDING without signal_id
    if (t.status === TradeStatus.PENDING && !t.signal_id) {
      flags.push({
        trade_id: t.trade_id,
        type: "ORPHANED",
        message: `PENDING trade ${t.trade_id.slice(0, 8)} has no signal_id`,
      });
    }

    // Lot mismatch: lot_size <= 0
    if (t.lot_size !== undefined && t.lot_size <= 0) {
      flags.push({
        trade_id: t.trade_id,
        type: "LOT_MISMATCH",
        message: `Trade ${t.trade_id.slice(0, 8)} has invalid lot_size ${t.lot_size}`,
      });
    }
  }

  return flags;
}

// ─── Exposure aggregation ────────────────────────────────────

export interface ExposureEntry {
  key: string;
  direction: "BUY" | "SELL" | "MIXED";
  totalLot: number;
  openCount: number;
  totalRiskPercent: number;
  unrealizedPnl: number;
}

function aggregateExposure(
  trades: Trade[],
  groupBy: "pair" | "account"
): ExposureEntry[] {
  const map = new Map<string, ExposureEntry>();

  for (const t of trades) {
    if (t.status !== TradeStatus.OPEN && t.status !== TradeStatus.PENDING) continue;
    const key = groupBy === "pair" ? (t.pair ?? "UNKNOWN") : (t.account_id ?? "UNKNOWN");
    const existing = map.get(key);
    if (!existing) {
      map.set(key, {
        key,
        direction: t.direction ?? "BUY",
        totalLot: t.lot_size ?? 0,
        openCount: 1,
        totalRiskPercent: t.total_risk_percent ?? 0,
        unrealizedPnl: t.pnl ?? 0,
      });
    } else {
      const newDir =
        existing.direction === t.direction ? existing.direction : "MIXED";
      map.set(key, {
        ...existing,
        direction: newDir,
        totalLot: existing.totalLot + (t.lot_size ?? 0),
        openCount: existing.openCount + 1,
        totalRiskPercent: existing.totalRiskPercent + (t.total_risk_percent ?? 0),
        unrealizedPnl: existing.unrealizedPnl + (t.pnl ?? 0),
      });
    }
  }

  return Array.from(map.values()).sort((a, b) => b.totalLot - a.totalLot);
}

// ─── Main hook ───────────────────────────────────────────────

export type TradeDeskTab = "pending" | "open" | "closed" | "cancelled";

export interface TradeDeskState {
  // Data
  allTrades: Trade[];
  pendingTrades: Trade[];
  openTrades: Trade[];
  closedTrades: Trade[];
  cancelledTrades: Trade[];
  accounts: Account[];

  // WS status
  wsStatus: string;
  isStale: boolean;

  // Selected
  selectedTrade: Trade | null;
  setSelectedTrade: (t: Trade | null) => void;

  // Tab
  activeTab: TradeDeskTab;
  setActiveTab: (tab: TradeDeskTab) => void;

  // Anomalies
  mismatchFlags: MismatchFlag[];

  // Exposure
  exposureByPair: ExposureEntry[];
  exposureByAccount: ExposureEntry[];

  // Loading states
  isLoading: boolean;
  isFetching: boolean;

  // Mutations
  handleConfirm: (tradeId: string) => Promise<void>;
  handleClose: (tradeId: string, reason: CloseReason) => Promise<void>;
  mutating: boolean;
  mutateError: string | null;

  // Pagination (for closed tab)
  page: number;
  pageSize: number;
  setPage: (p: number) => void;
}

export function useTradeDeskState(): TradeDeskState {
  const [activeTab, setActiveTab] = useState<TradeDeskTab>("open");
  const [selectedTrade, _setSelectedTrade] = useState<Trade | null>(null);
  const [mutating, setMutating] = useState(false);
  const [mutateError, setMutateError] = useState<string | null>(null);

  // Pagination state for closed/cancelled tabs
  const tableQuery = useTableQueryStore((state) => state.trades);
  const setTableQuery = useTableQueryStore((state) => state.setTrades);

  // ── REST bootstrap ──
  const { data: activeTradesData, isLoading: activeLoading, mutate: mutateActive } =
    useActiveTrades();
  const { data: accounts } = useAccounts();

  // Normalise active trades response
  const initialTrades = useMemo<Trade[]>(() => {
    if (!activeTradesData) return [];
    if (Array.isArray(activeTradesData)) return activeTradesData;
    return (activeTradesData as { trades?: Trade[] }).trades ?? [];
  }, [activeTradesData]);

  // ── History (closed/cancelled) ──
  const { data: historyData, isLoading: historyLoading, isFetching } =
    useTradesQuery(undefined, tableQuery.page, tableQuery.pageSize);

  const historyTrades = useMemo<Trade[]>(() => {
    if (!historyData) return [];
    return Array.isArray(historyData) ? historyData : [];
  }, [historyData]);

  // ── WS live merge on active ──
  const { trades: liveTrades, status: wsStatus, isStale } = useLiveTrades(
    initialTrades,
    true
  );

  // ── Merge live + history ──
  const allTrades = useMemo(() => {
    const liveIds = new Set(liveTrades.map((t) => t.trade_id));
    const uniqueHistory = historyTrades.filter((t) => !liveIds.has(t.trade_id));
    return [...liveTrades, ...uniqueHistory];
  }, [liveTrades, historyTrades]);

  // ── Partition ──
  const pendingTrades = useMemo(
    () => allTrades.filter((t) => t.status === TradeStatus.PENDING || t.status === "INTENDED" as TradeStatus),
    [allTrades]
  );
  const openTrades = useMemo(
    () => allTrades.filter((t) => t.status === TradeStatus.OPEN),
    [allTrades]
  );
  const closedTrades = useMemo(
    () => allTrades.filter((t) => t.status === TradeStatus.CLOSED),
    [allTrades]
  );
  const cancelledTrades = useMemo(
    () => allTrades.filter((t) => t.status === TradeStatus.CANCELLED || t.status === TradeStatus.SKIPPED),
    [allTrades]
  );

  // ── Keep selectedTrade stable across WS updates ──
  const selectedIdRef = useRef<string | null>(null);
  const setSelectedTrade = useCallback((t: Trade | null) => {
    selectedIdRef.current = t?.trade_id ?? null;
    _setSelectedTrade(t);
  }, []);

  // Sync selected trade when live trades update
  useEffect(() => {
    if (!selectedIdRef.current) return;
    const updated = allTrades.find((t) => t.trade_id === selectedIdRef.current);
    if (updated) _setSelectedTrade(updated);
  }, [allTrades]);

  // ── Anomaly detection ──
  const mismatchFlags = useMemo(
    () => detectMismatches([...pendingTrades, ...openTrades]),
    [pendingTrades, openTrades]
  );

  // ── Exposure ──
  const exposureByPair = useMemo(
    () => aggregateExposure(allTrades, "pair"),
    [allTrades]
  );
  const exposureByAccount = useMemo(
    () => aggregateExposure(allTrades, "account"),
    [allTrades]
  );

  // ── Mutations ──
  const handleConfirm = useCallback(async (tradeId: string) => {
    setMutating(true);
    setMutateError(null);
    try {
      await confirmTrade(tradeId);
      await mutateActive();
    } catch (e) {
      setMutateError(e instanceof Error ? e.message : "Confirm failed");
    } finally {
      setMutating(false);
    }
  }, [mutateActive]);

  const handleClose = useCallback(
    async (tradeId: string, reason: CloseReason) => {
      setMutating(true);
      setMutateError(null);
      try {
        await closeTrade(tradeId, reason);
        await mutateActive();
        if (selectedIdRef.current === tradeId) setSelectedTrade(null);
      } catch (e) {
        setMutateError(e instanceof Error ? e.message : "Close failed");
      } finally {
        setMutating(false);
      }
    },
    [mutateActive, setSelectedTrade]
  );

  return {
    allTrades,
    pendingTrades,
    openTrades,
    closedTrades,
    cancelledTrades,
    accounts: Array.isArray(accounts) ? accounts : [],

    wsStatus,
    isStale,

    selectedTrade,
    setSelectedTrade,

    activeTab,
    setActiveTab,

    mismatchFlags,

    exposureByPair,
    exposureByAccount,

    isLoading: activeLoading || historyLoading,
    isFetching,

    handleConfirm,
    handleClose,
    mutating,
    mutateError,

    page: tableQuery.page,
    pageSize: tableQuery.pageSize,
    setPage: (p) => setTableQuery({ page: p }),
  };
}
