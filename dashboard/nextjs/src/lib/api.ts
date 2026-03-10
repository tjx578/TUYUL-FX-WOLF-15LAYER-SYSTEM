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
  CalendarDayResponse,
  CalendarUpcomingResponse,
  CalendarBlockerResponse,
  CalendarHealthResponse,
  EALog,
  EAStatus,
  PropFirmPhase,
  PropFirmStatus,
} from "@/types";
import type { PipelineData } from "@/components/PipelinePanel";
import { getApiBaseUrl } from "@/lib/env";
import { bearerHeader } from "@/lib/auth";

const API_BASE = getApiBaseUrl();

export const API_ENDPOINTS = {
  health: "/health",
  accounts: "/api/v1/accounts",
  accountsRiskSnapshot: "/api/v1/accounts/risk-snapshot",
  tradesActive: "/api/v1/trades/active",
  tradesTake: "/api/v1/trades/take",
  tradesSkip: "/api/v1/trades/skip",
  tradesConfirmById: (tradeId: string) => `/api/v1/trades/${tradeId}/confirm`,
  tradesClose: "/api/v1/trades/close",
  riskSnapshotByAccount: (accountId: string) => `/api/v1/risk/${accountId}/snapshot`,
  riskPreviewMulti: "/api/v1/risk/preview-multi",
  verdictAll: "/api/v1/verdict/all",
  context: "/api/v1/context",
  execution: "/api/v1/execution",
  calendar: "/api/v1/calendar",
  calendarUpcoming: "/api/v1/calendar/upcoming",
  calendarBlocker: "/api/v1/calendar/blocker",
  calendarHealth: "/api/v1/calendar/health",
  eaStatus: "/api/v1/ea/status",
  eaLogs: "/api/v1/ea/logs",
  eaRestart: "/api/v1/ea/restart",
  eaSafeMode: "/api/v1/ea/safe-mode",
  propFirmStatus: (accountId: string) => `/api/v1/prop-firm/${accountId}/status`,
  propFirmPhase: (accountId: string) => `/api/v1/prop-firm/${accountId}/phase`,
  configProfile: "/api/v1/config/profile",
  configProfileByName: (profileName: string) => `/api/v1/config/profile/${profileName}`,
  configActive: "/api/v1/config/profile/active",
  configEffective: "/api/v1/config/profile/effective",
  configOverrides: "/api/v1/config/profile/overrides",
  configOverrideLegacy: "/api/v1/config/profile/override",
  configLock: "/api/v1/config/profile/lock",
  configProfilesLegacy: "/api/v1/config/profiles",
} as const;

const fetcher = async (url: string) => {
  const auth = bearerHeader();
  const res = await fetch(`${API_BASE}${url}`, {
    headers: {
      ...(auth ? { Authorization: auth } : {}),
    },
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch data: ${res.status} ${res.statusText}`);
  }

  return res.json();
};

const apiMutate = async (url: string, body?: unknown, method = "POST") => {
  return apiMutateWithHeaders(url, body, method);
};

const apiMutateWithHeaders = async (
  url: string,
  body?: unknown,
  method = "POST",
  headers?: Record<string, string>
) => {
  const governanceHeaders: Record<string, string> =
    method.toUpperCase() === "GET"
      ? {}
      : {
          "X-Edit-Mode": "ON",
          "X-Action-Reason": "UI_WRITE_ACTION",
          ...(process.env.NEXT_PUBLIC_ACTION_PIN
            ? { "X-Action-Pin": process.env.NEXT_PUBLIC_ACTION_PIN }
            : {}),
        };

  const auth = bearerHeader();
  const res = await fetch(`${API_BASE}${url}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: auth } : {}),
      ...governanceHeaders,
      ...(headers ?? {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }

  return res.json().catch(() => undefined);
};

export interface ActiveTradesResponse {
  trades: Trade[];
  count: number;
}

// ─── HOOKS ───────────────────────────────────────────────────

export function useAccounts() {
  const { data, error, isLoading } = useSWR<Account[] | { accounts: Account[] }>(
    API_ENDPOINTS.accounts,
    fetcher
  );
  const normalized = Array.isArray(data)
    ? data
    : Array.isArray(data?.accounts)
      ? data.accounts
      : [];
  return { data: normalized, isLoading, isError: !!error, error };
}

export function useActiveTrades() {
  // Current backend shape: { trades: [...], count: n }
  // Keep union for backward compatibility with legacy Trade[] responses.
  const { data, error, isLoading, mutate } = useSWR<
    ActiveTradesResponse | Trade[]
  >(
    API_ENDPOINTS.tradesActive,
    fetcher
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useAllVerdicts() {
  const { data, error, isLoading, mutate } = useSWR<L12Verdict[] | Record<string, L12Verdict>>(
    API_ENDPOINTS.verdictAll,
    fetcher
  );
  const normalized = Array.isArray(data) ? data : Object.values(data ?? {});
  return { data: normalized, isLoading, isError: !!error, error, mutate };
}

export function useHealth() {
  const { data, error, isLoading } = useSWR<SystemHealth>(
    API_ENDPOINTS.health,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useContext() {
  const { data, error, isLoading } = useSWR<ContextSnapshot>(
    API_ENDPOINTS.context,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useExecution() {
  const { data, error, isLoading } = useSWR<ExecutionState>(
    API_ENDPOINTS.execution,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useRiskSnapshot(accountId: string) {
  const { data, error, isLoading } = useSWR<RiskSnapshot>(
    accountId ? API_ENDPOINTS.riskSnapshotByAccount(accountId) : null,
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
  const params = new URLSearchParams();
  if (impact) params.set("impact", impact);
  const endpoint = period === "upcoming"
    ? `${API_ENDPOINTS.calendarUpcoming}?${params.toString()}`
    : `${API_ENDPOINTS.calendar}?${params.toString()}`;
  const { data, error, isLoading } = useSWR<CalendarDayResponse | CalendarUpcomingResponse | CalendarEvent[]>(
    endpoint,
    fetcher
  );
  const raw = Array.isArray(data)
    ? data
    : Array.isArray(data?.events)
      ? data.events
      : [];

  const normalized = raw.map((item: CalendarEvent) => {
    const title = item.title ?? item.event ?? "";
    const eventId = item.id ?? item.canonical_id ?? `${item.currency}:${title}:${item.time}`;
    return {
      ...item,
      id: eventId,
      event: item.event ?? title,
      title,
    } as CalendarEvent;
  });

  return { data: normalized as CalendarEvent[], isLoading, isError: !!error, error };
}

export function useCalendarBlocker(symbol?: string) {
  const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
  const { data, error, isLoading, mutate } = useSWR<CalendarBlockerResponse>(
    `${API_ENDPOINTS.calendarBlocker}${query}`,
    fetcher
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useCalendarSourceHealth() {
  const { data, error, isLoading, mutate } = useSWR<CalendarHealthResponse>(
    API_ENDPOINTS.calendarHealth,
    fetcher
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useEAStatus() {
  const { data, error, isLoading } = useSWR<EAStatus>(
    API_ENDPOINTS.eaStatus,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function useEALogs() {
  const { data, error, isLoading, mutate } = useSWR<EALog[]>(
    API_ENDPOINTS.eaLogs,
    fetcher
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function usePropFirmPhase(accountId: string) {
  const { data, error, isLoading } = useSWR<PropFirmPhase>(
    accountId ? API_ENDPOINTS.propFirmPhase(accountId) : null,
    fetcher
  );
  return { data, isLoading, isError: !!error, error };
}

export function usePropFirmStatus(accountId: string) {
  const { data, error, isLoading } = useSWR<PropFirmStatus>(
    accountId ? API_ENDPOINTS.propFirmStatus(accountId) : null,
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

export interface AccountRiskSnapshot {
  account_id: string;
  daily_dd_percent: number;
  total_dd_percent: number;
  open_risk_percent: number;
  max_concurrent: number;
  open_trades: number;
  circuit_breaker: boolean;
  status: "SAFE" | "WARNING" | "CRITICAL";
}

export function useAccountsRiskSnapshot() {
  const { data, error, isLoading, mutate } = useSWR<AccountRiskSnapshot[]>(
    API_ENDPOINTS.accountsRiskSnapshot,
    fetcher
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

// ─── MUTATIONS ────────────────────────────────────────────────

export async function confirmTrade(tradeId: string): Promise<void> {
  await apiMutateWithHeaders(
    API_ENDPOINTS.tradesConfirmById(tradeId),
    undefined,
    "POST",
    { "X-Idempotency-Key": `confirm:${tradeId}` }
  );
}

export async function closeTrade(tradeId: string, reason: string): Promise<void> {
  await apiMutate(API_ENDPOINTS.tradesClose, { trade_id: tradeId, reason });
}

export interface TakeSignalRequest {
  verdict_id: string;
  accounts: string[];
  pair: string;
  direction: "BUY" | "SELL";
  entry: number;
  sl: number;
  tp: number;
  risk_percent: number;
  operator?: string;
}

export async function takeSignal(req: TakeSignalRequest): Promise<void> {
  await apiMutate("/api/v1/signals/take", req);
}

export interface RiskPreviewMultiRequest {
  verdict_id: string;
  accounts: Array<{ account_id: string }>;
  risk_percent: number;
  risk_mode: "FIXED" | "SPLIT";
}

export interface RiskPreviewAccountItem {
  account_id: string;
  lot_size: number;
  risk_percent: number;
  daily_dd_after: number;
  allowed: boolean;
  reason?: string;
}

export async function previewRiskMulti(
  req: RiskPreviewMultiRequest
): Promise<{ previews: RiskPreviewAccountItem[] }> {
  return apiMutate(API_ENDPOINTS.riskPreviewMulti, req);
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
  return apiMutate(API_ENDPOINTS.accounts, {
    account_name: data.account_name,
    broker: data.broker,
    currency: data.currency,
    starting_balance: data.balance,
    current_balance: data.balance,
    equity: data.equity || data.balance,
    equity_high: data.equity || data.balance,
    leverage: 100,
    commission_model: "standard",
    notes: "",
    data_source: "MANUAL",
    prop_firm: Boolean(data.prop_firm_code),
    max_daily_dd_percent: 4,
    max_total_dd_percent: 8,
    max_concurrent_trades: 1,
    reason: "ACCOUNT_CREATE_FROM_UI",
  });
}

export async function restartEA(): Promise<void> {
  await apiMutate(API_ENDPOINTS.eaRestart, { reason: "MANUAL_RESTART" });
}

export async function setEASafeMode(enabled: boolean, reason: string): Promise<void> {
  await apiMutate(API_ENDPOINTS.eaSafeMode, { enabled, reason });
}
