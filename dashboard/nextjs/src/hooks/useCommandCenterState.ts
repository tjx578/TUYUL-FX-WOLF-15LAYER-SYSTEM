"use client";

// ============================================================
// TUYUL FX Wolf-15 — Command Center Orchestration Hook
// PRD: useCommandCenterState
// Wires: REST snapshot → WS live merge (verdicts + risk)
// Derives: topActionableSignals, criticalAlerts, isSystemDegraded, isStale
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
import { useAlertsWS } from "@/lib/websocket";
import { useSystemStore } from "@/store/useSystemStore";
import type { L12Verdict, Trade, Account } from "@/types";

// ── helpers ─────────────────────────────────────────────────

function verdictIsActionable(v: L12Verdict): boolean {
  const notExpired =
    !v.expires_at || v.expires_at > Math.floor(Date.now() / 1000);
  return String(v.verdict ?? "").startsWith("EXECUTE") && notExpired;
}

function urgencyScore(v: L12Verdict): number {
  return (v.confidence ?? 0) * (v.risk_reward_ratio ?? 1);
}

// ── hook ─────────────────────────────────────────────────────

export interface CommandCenterState {
  // raw data
  verdictList: L12Verdict[];
  activeTrades: Trade[];
  accounts: Account[];
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
  // ── REST snapshots ────────────────────────────────────────
  const { data: verdictsRaw, isLoading: vLoading, isError: vError } = useAllVerdicts();
  const { data: activeTradesData, isError: tradesError } = useActiveTrades();
  const { data: context, isError: contextError } = useContext();
  const { data: execution, isError: executionError } = useExecution();
  const { data: accounts, isError: accountsError } = useAccounts();
  const { data: riskSnapshots, isError: riskError } = useAccountsRiskSnapshot();
  const { data: health } = useHealth();
  const { data: calendarBlocker } = useCalendarBlocker();
  const { alerts } = useAlertsWS();

  const wsStatus = useSystemStore((s) => s.wsStatus);
  const mode = useSystemStore((s) => s.mode);

  // ── REST → initial normalisation ─────────────────────────
  const restVerdicts = useMemo<L12Verdict[]>(
    () => (Array.isArray(verdictsRaw) ? verdictsRaw : []),
    [verdictsRaw]
  );

  // ── WS live merge for verdicts (REST bootstrap) ───────────
  const {
    verdicts: verdictList,
    status: liveStatus,
    isStale: verdictStale,
  } = useLiveSignals(restVerdicts, true);

  // ── Normalise active trades ───────────────────────────────
  const activeTrades = useMemo<Trade[]>(() => {
    if (!activeTradesData) return [];
    if (Array.isArray(activeTradesData)) return activeTradesData as Trade[];
    const resp = activeTradesData as ActiveTradesResponse;
    return Array.isArray(resp.trades) ? resp.trades : [];
  }, [activeTradesData]);

  const snapshotList = useMemo<AccountRiskSnapshot[]>(
    () => (Array.isArray(riskSnapshots) ? riskSnapshots : []),
    [riskSnapshots]
  );

  // ── Derived state ─────────────────────────────────────────
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

  const criticalSnapshots = useMemo(
    () => snapshotList.filter((s) => s.status === "CRITICAL" || s.circuit_breaker),
    [snapshotList]
  );

  const warnSnapshots = useMemo(
    () => snapshotList.filter((s) => s.status === "WARNING" && !s.circuit_breaker),
    [snapshotList]
  );

  const isSystemDegraded =
    mode === "DEGRADED" ||
    wsStatus === "DISCONNECTED" ||
    wsStatus === "RECONNECTING" ||
    liveStatus === "DEGRADED" ||
    liveStatus === "STALE" ||
    health?.status !== "ok";

  const isStale = verdictStale;

  const dataErrors = useMemo(() => {
    const errs: string[] = [];
    if (vError)         errs.push("verdicts");
    if (tradesError)    errs.push("trades");
    if (contextError)   errs.push("context");
    if (executionError) errs.push("execution");
    if (accountsError)  errs.push("accounts");
    if (riskError)      errs.push("risk");
    return errs;
  }, [vError, tradesError, contextError, executionError, accountsError, riskError]);

  const recentAlerts = useMemo(() => alerts.slice(0, 6), [alerts]);

  return {
    verdictList,
    activeTrades,
    accounts,
    snapshotList,
    context,
    execution,
    health,
    calendarBlocker,
    recentAlerts,
    topActionableSignals,
    executeCount,
    highConfidence,
    criticalSnapshots,
    warnSnapshots,
    isSystemDegraded,
    isStale,
    wsStatus,
    mode,
    dataErrors,
    vLoading,
  };
}
