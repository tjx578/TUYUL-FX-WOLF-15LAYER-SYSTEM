import useSWR from "swr";
import type {
  L12Verdict,
  Trade,
  AccountCreate,
  Account,
  JournalMetrics,
  DailyJournal,
  RiskSnapshot,
  SystemHealth,
  ContextSnapshot,
  ExecutionState,
  PairInfo,
  PriceData,
  ProbabilitySummary,
  ProbabilityCalibration,
  CalendarEvent,
  EALog,
  EAStatus,
  PropFirmPhase,
  PropFirmStatus,
} from "@/types";
import type { PipelineData } from "@/components/PipelinePanel";
import { getApiBaseUrl } from "@/lib/env";

const API_BASE = getApiBaseUrl();

const fetcher = async (url: string) => {
  const res = await fetch(`${API_BASE}${url}`, {
    credentials: "include",
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch data: ${res.status} ${res.statusText}`);
  }

  return res.json();
};

const apiMutate = async (url: string, body?: unknown, method = "POST") => {
  const res = await fetch(`${API_BASE}${url}`, {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }

  return res.json().catch(() => undefined);
};

// ─── HOOKS ───────────────────────────────────────────────────

export function useAccounts() {
  const { data, error, isLoading } = useSWR<Account[]>(
    "/api/v1/accounts",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useActiveTrades() {
  const { data, error, isLoading, mutate } = useSWR<Trade[]>(
    "/api/v1/trades/active",
    fetcher
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useAllVerdicts() {
  const { data, error, isLoading, mutate } = useSWR<L12Verdict[]>(
    "/api/v1/verdicts",
    fetcher
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useHealth() {
  const { data, error, isLoading } = useSWR<SystemHealth>(
    "/api/v1/health",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useContext() {
  const { data, error, isLoading } = useSWR<ContextSnapshot>(
    "/api/v1/context",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useExecution() {
  const { data, error, isLoading } = useSWR<ExecutionState>(
    "/api/v1/execution/state",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useRiskSnapshot(accountId: string) {
  const { data, error, isLoading } = useSWR<RiskSnapshot>(
    accountId ? `/api/v1/risk/snapshot/${accountId}` : null,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function usePipeline(pair: string) {
  const { data, error, isLoading } = useSWR<PipelineData>(
    pair ? `/api/v1/pipeline/${pair}` : null,
    fetcher
  );
  return { data, error, isLoading };
}

export function useCalendarEvents(period = "today", impact?: string) {
  const query = impact ? `?impact=${impact}` : "";
  const { data, error, isLoading } = useSWR<CalendarEvent[]>(
    `/api/v1/calendar/${period}${query}`,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useEAStatus() {
  const { data, error, isLoading } = useSWR<EAStatus>(
    "/api/v1/ea/status",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useEALogs() {
  const { data, error, isLoading, mutate } = useSWR<EALog[]>(
    "/api/v1/ea/logs",
    fetcher
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function usePropFirmPhase(accountId: string) {
  const { data, error, isLoading } = useSWR<PropFirmPhase>(
    accountId ? `/api/v1/propfirm/${accountId}/phase` : null,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function usePropFirmStatus(accountId: string) {
  const { data, error, isLoading } = useSWR<PropFirmStatus>(
    accountId ? `/api/v1/propfirm/${accountId}/status` : null,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function usePricesREST() {
  const { data, error, isLoading } = useSWR<PriceData[]>(
    "/api/v1/prices",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function usePairs() {
  const { data, error, isLoading } = useSWR<PairInfo[]>(
    "/api/v1/pairs",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useProbabilitySummary() {
  const { data, error, isLoading } = useSWR<ProbabilitySummary>(
    "/api/v1/probability/summary",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useProbabilityCalibration() {
  const { data, error, isLoading } = useSWR<ProbabilityCalibration>(
    "/api/v1/probability/calibration",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useJournalToday() {
  const { data, error, isLoading } = useSWR<DailyJournal>(
    "/api/v1/journal/today",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useJournalWeekly() {
  const { data, error, isLoading } = useSWR<DailyJournal[]>(
    "/api/v1/journal/weekly",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useJournalMetrics() {
  const { data, error, isLoading } = useSWR<JournalMetrics>(
    "/api/v1/journal/metrics",
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

// ─── MUTATIONS ────────────────────────────────────────────────

export async function confirmTrade(tradeId: string): Promise<void> {
  await apiMutate(`/api/v1/trades/${tradeId}/confirm`);
}

export async function closeTrade(tradeId: string, reason: string): Promise<void> {
  await apiMutate(`/api/v1/trades/${tradeId}/close`, { reason });
}

export interface TakeSignalRequest {
  signal_id: string;
  account_id: string;
  pair: string;
  direction: "BUY" | "SELL";
  entry: number;
  sl: number;
  tp: number;
  risk_percent: number;
  risk_mode: "FIXED" | "SPLIT";
}

export async function takeSignal(req: TakeSignalRequest): Promise<void> {
  await apiMutate("/api/v1/signals/take", req);
}

export interface SkipSignalRequest {
  signal_id: string;
  pair?: string;
  reason?: string;
}

export async function skipSignal(req: SkipSignalRequest): Promise<void> {
  await apiMutate("/api/v1/signals/skip", req);
}

export async function createAccount(data: AccountCreate): Promise<Account> {
  return apiMutate("/api/v1/accounts", data);
}

export async function restartEA(): Promise<void> {
  await apiMutate("/api/v1/ea/restart");
}
