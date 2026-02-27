// ============================================================
// TUYUL FX Wolf-15 — API Client + SWR Hooks
// Mirrors: api/dashboard_routes.py + api/l12_routes.py
// ============================================================

import useSWR from "swr";
import type {
  L12Verdict,
  Trade,
  Account,
  AccountCreate,
  JournalMetrics,
  DailyJournal,
  RiskSnapshot,
  SystemHealth,
  ContextSnapshot,
  ExecutionState,
  PairInfo,
  PriceData,
  ProbabilitySummary,
  ProbabilityMetrics,
  CalendarEvent,
  EALog,
  EAStatus,
  PropFirmPhase,
} from "@/types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── AUTH HELPERS ─────────────────────────────────────────────

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("wolf15_token");
}

function authHeaders(): HeadersInit {
  const token = getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

// ─── BASE FETCHER ─────────────────────────────────────────────

async function fetcher<T = unknown>(url: string): Promise<T> {
  const res = await fetch(`${API_URL}${url}`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

async function poster<T = unknown>(
  url: string,
  body: unknown
): Promise<T> {
  const res = await fetch(`${API_URL}${url}`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ─── SWR CONFIG DEFAULTS ──────────────────────────────────────

const FAST = { refreshInterval: 3000 };
const NORMAL = { refreshInterval: 5000 };
const SLOW = { refreshInterval: 10000 };
const LAZY = { refreshInterval: 30000 };
const ONCE = { revalidateOnFocus: false };

// ─── L12 VERDICT HOOKS ────────────────────────────────────────

export function useVerdict(pair: string) {
  return useSWR<L12Verdict>(
    pair ? `/api/v1/l12/${pair}` : null,
    fetcher,
    NORMAL
  );
}

export function useAllVerdicts() {
  return useSWR<Record<string, L12Verdict>>(
    "/api/v1/verdict/all",
    fetcher,
    NORMAL
  );
}

export function useContext() {
  return useSWR<ContextSnapshot>(
    "/api/v1/context",
    fetcher,
    SLOW
  );
}

export function useExecution() {
  return useSWR<ExecutionState>(
    "/api/v1/execution",
    fetcher,
    NORMAL
  );
}

export function usePairs() {
  return useSWR<PairInfo[]>("/api/v1/pairs", fetcher, ONCE);
}

// ─── PIPELINE HOOKS ───────────────────────────────────────────

export function usePipeline(pair: string | null) {
  return useSWR(
    pair ? `/api/v1/pipeline/${pair}` : null,
    fetcher,
    NORMAL
  );
}

// ─── HEALTH ───────────────────────────────────────────────────

export function useHealth() {
  return useSWR<SystemHealth>("/health", fetcher, LAZY);
}

// ─── TRADE HOOKS ──────────────────────────────────────────────

export function useActiveTrades() {
  return useSWR<Trade[]>("/api/v1/trades/active", fetcher, FAST);
}

export function useTrade(tradeId: string) {
  return useSWR<Trade>(
    tradeId ? `/api/v1/trades/${tradeId}` : null,
    fetcher,
    { refreshInterval: 2000 }
  );
}

// ─── JOURNAL HOOKS ────────────────────────────────────────────

export function useJournalToday() {
  return useSWR<DailyJournal>("/api/v1/journal/today", fetcher, SLOW);
}

export function useJournalWeekly() {
  return useSWR<DailyJournal[]>(
    "/api/v1/journal/weekly",
    fetcher,
    LAZY
  );
}

export function useJournalMetrics() {
  return useSWR<JournalMetrics>(
    "/api/v1/journal/metrics",
    fetcher,
    { refreshInterval: 15000 }
  );
}

// ─── ACCOUNT HOOKS ────────────────────────────────────────────

export function useAccounts() {
  return useSWR<Account[]>("/api/v1/accounts", fetcher, LAZY);
}

export function useAccount(accountId: string) {
  return useSWR<Account>(
    accountId ? `/api/v1/accounts/${accountId}` : null,
    fetcher,
    SLOW
  );
}

// ─── RISK HOOKS ───────────────────────────────────────────────

export function useRiskSnapshot(accountId: string) {
  return useSWR<RiskSnapshot>(
    accountId ? `/api/v1/risk/${accountId}/snapshot` : null,
    fetcher,
    NORMAL
  );
}

// ─── PRICE HOOKS ──────────────────────────────────────────────

export function usePricesREST() {
  return useSWR<PriceData[]>("/api/v1/prices", fetcher, {
    refreshInterval: 2000,
  });
}

// ─── PROBABILITY HOOKS ────────────────────────────────────────

export function useProbabilitySummary() {
  return useSWR<ProbabilitySummary>(
    "/api/v1/probability/summary",
    fetcher,
    SLOW
  );
}

export function useProbabilityCalibration() {
  return useSWR<{ grade: string; score: number; details: string[] }>(
    "/api/v1/probability/calibration",
    fetcher,
    LAZY
  );
}

export function useSignalProbability(signalId: string) {
  return useSWR<ProbabilityMetrics>(
    signalId ? `/api/v1/signals/${signalId}/probability` : null,
    fetcher,
    ONCE
  );
}

// ─── WRITE ACTIONS ────────────────────────────────────────────

export interface TakeSignalRequest {
  signal_id: string;
  account_id: string;
  pair: string;
  direction: "BUY" | "SELL";
  entry: number;
  sl: number;
  tp: number;
  risk_percent: number;
  risk_mode?: "FIXED" | "SPLIT";
  split_ratio?: number;
}

export async function takeSignal(
  data: TakeSignalRequest
): Promise<{ trade_id: string; lot_size: number; risk_calc: unknown }> {
  return poster("/api/v1/trades/take", data);
}

export async function skipSignal(data: {
  signal_id: string;
  pair: string;
  reason?: string;
}): Promise<{ logged: boolean }> {
  return poster("/api/v1/trades/skip", data);
}

export async function confirmTrade(
  tradeId: string
): Promise<{ trade_id: string; status: string }> {
  return poster("/api/v1/trades/confirm", { trade_id: tradeId });
}

export async function closeTrade(
  tradeId: string,
  reason?: string
): Promise<{ trade_id: string; status: string; pnl: number }> {
  return poster("/api/v1/trades/close", {
    trade_id: tradeId,
    reason: reason ?? "MANUAL_CLOSE",
  });
}

export async function createAccount(
  data: AccountCreate
): Promise<Account> {
  return poster("/api/v1/accounts", data);
}

// ─── EA HOOKS ─────────────────────────────────────────────────

export const useEAStatus = () => useSWR<EAStatus>("/api/v1/ea/status", fetcher);
export const useEALogs = () => useSWR<EALog[]>("/api/v1/ea/logs", fetcher);
export const restartEA = async () => poster("/api/v1/ea/restart", {});

export const usePropFirmStatus = (accountId: string) =>
  useSWR(`/api/v1/prop-firm/${accountId}/status`, fetcher);

export const usePropFirmPhase = (accountId: string) =>
  useSWR<PropFirmPhase>(`/api/v1/prop-firm/${accountId}/phase`, fetcher);

export const useCalendarEvents = (date = "today", impact = "HIGH") =>
  useSWR<CalendarEvent[]>(`/api/v1/calendar?date=${date}&impact=${impact}`, fetcher);

