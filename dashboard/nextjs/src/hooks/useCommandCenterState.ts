"use client";

// ============================================================
// TUYUL FX Wolf-15 — Command Center Orchestration Hook
// PRD: useCommandCenterState
// Wires: REST snapshot → WS live merge (verdicts + risk)
// Derives: topActionableSignals, criticalAlerts, isSystemDegraded, isStale
//
// Split into granular sub-hooks to prevent re-render cascades.
// Components should prefer using individual sub-hooks (e.g.
// useCommandCenterVerdicts, useCommandCenterStatus) rather than
// the full useCommandCenterState if they only need a slice.
// ============================================================

import { useMemo } from "react";
import {
  useAllVerdicts,
  useActiveTrades,
  useContext,
  useExecution,
  useAccounts,
  useAccountsRiskSnapshot,
  useHealth,
  useCalendarBlocker,
  type ActiveTradesResponse,
  type AccountRiskSnapshot,
} from "@/lib/api";
import { useLiveSignals } from "@/lib/realtime/hooks/useLiveSignals";
import { useLiveAlerts } from "@/lib/realtime";
import { useSystemStore } from "@/store/useSystemStore";
import type { L12Verdict, Trade, Account } from "@/types";

// ── helpers ─────────────────────────────────────────────────

function verdictIsActionable(v: L12Verdict): boolean {
  const notExpired =
    !v.expires_at || v.expires_at > Math.floor(Date.now() / 1000);
  const vs = String(v.verdict ?? "");
  const isExecute = vs === "EXECUTE_BUY" || vs === "EXECUTE_SELL";
  const hasDirection =
    v.direction === "BUY" || v.direction === "SELL" || isExecute;
  return isExecute && hasDirection && notExpired;
}

function urgencyScore(v: L12Verdict): number {
  return (v.confidence ?? 0) * (v.risk_reward_ratio ?? 1);
}

// ── Granular sub-hooks ──────────────────────────────────────

/**
 * Live-merged verdict list with WS overlay on REST bootstrap.
 * Only re-renders when verdicts or live signal status changes.
 */
export function useCommandCenterVerdicts() {
  const { data: verdictsRaw, isLoading: vLoading, isError: vError } = useAllVerdicts();

  const restVerdicts = useMemo<L12Verdict[]>(
    () => (Array.isArray(verdictsRaw) ? verdictsRaw : []),
    [verdictsRaw]
  );

  const {
    verdicts: verdictList,
    status: liveStatus,
    isStale: verdictStale,
  } = useLiveSignals(restVerdicts, true);

  const topActionableSignals = useMemo(
    () =>
      verdictList
        .filter(verdictIsActionable)
        .sort((a, b) => urgencyScore(b) - urgencyScore(a))
        .slice(0, 3),
    [verdictList]
  );

  const executeCount = useMemo(
    () => verdictList.filter((v) => String(v.verdict ?? "").startsWith("EXECUTE")).length,
    [verdictList]
  );

  const highConfidence = useMemo(
    () => verdictList.filter((v) => (v.confidence ?? 0) >= 0.75).length,
    [verdictList]
  );

  return useMemo(
    () => ({
      verdictList,
      topActionableSignals,
      executeCount,
      highConfidence,
      verdictStale,
      liveStatus,
      vLoading,
      vError,
    }),
    [verdictList, topActionableSignals, executeCount, highConfidence, verdictStale, liveStatus, vLoading, vError]
  );
}

/**
 * Active trades, normalised from REST.
 * Only re-renders when trades data changes.
 */
export function useCommandCenterTrades() {
  const { data: activeTradesData, isError: tradesError } = useActiveTrades();

  const activeTrades = useMemo<Trade[]>(() => {
    if (!activeTradesData) return [];
    if (Array.isArray(activeTradesData)) return activeTradesData as Trade[];
    const resp = activeTradesData as ActiveTradesResponse;
    return Array.isArray(resp.trades) ? resp.trades : [];
  }, [activeTradesData]);

  return useMemo(
    () => ({ activeTrades, tradesError }),
    [activeTrades, tradesError]
  );
}

/**
 * Account & risk snapshot data.
 * Only re-renders when account or risk data changes.
 */
export function useCommandCenterRisk() {
  const { data: accountsRaw, isError: accountsError } = useAccounts();
  const { data: riskSnapshots, isError: riskError } = useAccountsRiskSnapshot();

  const accounts = useMemo<Account[]>(
    () => (Array.isArray(accountsRaw) ? accountsRaw : []),
    [accountsRaw]
  );

  const snapshotList = useMemo<AccountRiskSnapshot[]>(
    () => (Array.isArray(riskSnapshots) ? riskSnapshots : []),
    [riskSnapshots]
  );

  const criticalSnapshots = useMemo(
    () => snapshotList.filter((s) => s.status === "CRITICAL" || s.circuit_breaker),
    [snapshotList]
  );

  const warnSnapshots = useMemo(
    () => snapshotList.filter((s) => s.status === "WARNING" && !s.circuit_breaker),
    [snapshotList]
  );

  return useMemo(
    () => ({ accounts, snapshotList, criticalSnapshots, warnSnapshots, accountsError, riskError }),
    [accounts, snapshotList, criticalSnapshots, warnSnapshots, accountsError, riskError]
  );
}

/**
 * System status: WS, mode, degradation, health.
 * Only re-renders when system status or health changes.
 */
export function useCommandCenterStatus() {
  const { data: context, isError: contextError } = useContext();
  const { data: execution, isError: executionError } = useExecution();
  const { data: health } = useHealth();
  const { data: calendarBlocker } = useCalendarBlocker();
  const { alerts } = useLiveAlerts();

  const wsStatus = useSystemStore((s: { wsStatus: string }) => s.wsStatus);
  const mode = useSystemStore((s: { mode: any; }) => s.mode);

  const recentAlerts = useMemo(() => alerts.slice(0, 6), [alerts]);

  return useMemo(
    () => ({
      context,
      execution,
      health,
      calendarBlocker,
      recentAlerts,
      wsStatus,
      mode,
      contextError,
      executionError,
    }),
    [context, execution, health, calendarBlocker, recentAlerts, wsStatus, mode, contextError, executionError]
  );
}

// ── Full composite hook (backward compatible) ───────────────

export interface CommandCenterState {
  // raw data
  verdictList: L12Verdict[];
  activeTrades: Trade[];
  accounts: Account[]; // always an array, never undefined
  snapshotList: AccountRiskSnapshot[];
  context: ReturnType<typeof useContext>["data"];
  execution: ReturnType<typeof useExecution>["data"];
  health: ReturnType<typeof useHealth>["data"];
  calendarBlocker: ReturnType<typeof useCalendarBlocker>["data"];
  recentAlerts: unknown[];

  // derived
  topActionableSignals: L12Verdict[];
  executeCount: number;
  highConfidence: number;
  criticalSnapshots: AccountRiskSnapshot[];
  warnSnapshots: AccountRiskSnapshot[];
  isSystemDegraded: boolean;
  isStale: boolean;
  wsStatus: string;
  mode: string;
  dataErrors: string[];

  // loading
  vLoading: boolean;
}

export function useCommandCenterState(): CommandCenterState {
  const verdicts = useCommandCenterVerdicts();
  const trades = useCommandCenterTrades();
  const risk = useCommandCenterRisk();
  const status = useCommandCenterStatus();

  const isSystemDegraded =
    status.mode === "DEGRADED" ||
    status.mode === "RECONNECTING_WS" ||
    status.mode === "POLLING_REST" ||
    status.mode === "STALE" ||
    status.wsStatus === "DISCONNECTED" ||
    status.wsStatus === "RECONNECTING" ||
    verdicts.liveStatus === "DEGRADED" ||
    verdicts.liveStatus === "STALE" ||
    status.health?.status !== "ok";

  const dataErrors = useMemo(() => {
    const errs: string[] = [];
    if (verdicts.vError) errs.push("verdicts");
    if (trades.tradesError) errs.push("trades");
    if (status.contextError) errs.push("context");
    if (status.executionError) errs.push("execution");
    if (risk.accountsError) errs.push("accounts");
    if (risk.riskError) errs.push("risk");
    return errs;
  }, [verdicts.vError, trades.tradesError, status.contextError, status.executionError, risk.accountsError, risk.riskError]);

  return {
    verdictList: verdicts.verdictList,
    activeTrades: trades.activeTrades,
    accounts: risk.accounts,
    snapshotList: risk.snapshotList,
    context: status.context,
    execution: status.execution,
    health: status.health,
    calendarBlocker: status.calendarBlocker,
    recentAlerts: status.recentAlerts,
    topActionableSignals: verdicts.topActionableSignals,
    executeCount: verdicts.executeCount,
    highConfidence: verdicts.highConfidence,
    criticalSnapshots: risk.criticalSnapshots,
    warnSnapshots: risk.warnSnapshots,
    isSystemDegraded,
    isStale: verdicts.verdictStale,
    wsStatus: status.wsStatus,
    mode: status.mode,
    dataErrors,
    vLoading: verdicts.vLoading,
  };
}
