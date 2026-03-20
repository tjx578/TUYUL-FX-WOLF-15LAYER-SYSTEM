import { useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  L12Verdict,
  Trade,
  AccountCreate,
  Account,
  CreateAccountRequest,
  CapitalDeploymentResponse,
  JournalMetrics,
  DailyJournal,
  RiskSnapshot,
  SystemHealth,
  OrchestratorState,
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
  EAAgent,
  PropFirmPhase,
  PropFirmStatus,
} from "@/types";
import type { PipelineData } from "@/components/panels/PipelinePanel";
import { bearerHeader } from "@/lib/auth";
import { HttpError } from "@/lib/fetcher";
import { useSessionStore } from "@/store/useSessionStore";

// Use relative paths — Next.js rewrites proxy /api/* to the backend.
const API_BASE = "";

// Global 429 cooldown — prevents all hooks from hammering a rate-limited backend.
let _rateLimitedUntil = 0;

export const API_ENDPOINTS = {
  health: "/health",
  orchestratorState: "/api/v1/orchestrator/state",
  accounts: "/api/v1/accounts",
  accountsRiskSnapshot: "/api/v1/accounts/risk-snapshot",
  accountsCapitalDeployment: "/api/v1/accounts/capital-deployment",
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
  eaAgents: "/api/v1/ea/agents",
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
  // Bail immediately if session is known-expired to avoid 401 flood:
  // when 10+ SWR hooks fire simultaneously after expiry, each would hit
  // the backend and get 401. Short-circuit here to prevent the cascade.
  if (useSessionStore.getState().expiredReason) {
    throw new HttpError("Session expired", 401);
  }

  // Bail if we're inside a 429 cooldown window — avoids hammering a rate-limited backend
  if (_rateLimitedUntil > Date.now()) {
    throw new HttpError("Rate limited — waiting for cooldown", 429);
  }

  const auth = bearerHeader();
  const res = await fetch(`${API_BASE}${url}`, {
    credentials: "include",
    headers: {
      ...(auth ? { Authorization: auth } : {}),
    },
  });

  if (res.status === 429) {
    const retryAfter = res.headers.get("Retry-After");
    _rateLimitedUntil = Date.now() + (retryAfter ? parseInt(retryAfter, 10) * 1000 : 60_000);
    throw new HttpError("Rate limited", 429);
  }

  if (!res.ok) {
    let info: unknown = null;
    try {
      info = await res.json();
    } catch {
      try {
        info = await res.text();
      } catch {
        info = null;
      }
    }
    throw new HttpError(
      `Request failed: ${res.status} ${res.statusText}`,
      res.status,
      info
    );
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
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: auth } : {}),
      ...governanceHeaders,
      ...(headers ?? {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let info: unknown = null;
    try {
      info = await res.json();
    } catch {
      try {
        info = await res.text();
      } catch {
        info = null;
      }
    }
    throw new HttpError(
      `Request failed: ${res.status} ${res.statusText}`,
      res.status,
      info
    );
  }

  return res.json().catch(() => undefined);
};

export interface ActiveTradesResponse {
  trades: Trade[];
  count: number;
}

// ─── HOOKS ───────────────────────────────────────────────────

// Wrapper to keep return shape consistent across all query hooks.
// mutate() returns a function that invalidates the query key,
// keeping the same invalidation ergonomics as SWR's mutate().
function useApiQuery<T>(
  key: string | null,
  opts?: { refetchInterval?: number },
) {
  const queryClient = useQueryClient();
  const { data, error, isLoading } = useQuery<T>({
    queryKey: [key],
    queryFn: () => fetcher(key!),
    enabled: !!key,
    ...(opts?.refetchInterval ? { refetchInterval: opts.refetchInterval } : {}),
  });
  const mutate = () => queryClient.invalidateQueries({ queryKey: [key] });
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useAccounts() {
  const { data, error, isLoading, mutate } = useApiQuery<Account[] | { accounts: Account[] }>(
    API_ENDPOINTS.accounts,
  );
  const normalized = Array.isArray(data)
    ? data
    : Array.isArray(data?.accounts)
      ? data.accounts
      : [];
  return { data: normalized, isLoading, isError: !!error, error, mutate };
}

export function useCapitalDeployment() {
  const { data, error, isLoading, mutate } = useApiQuery<CapitalDeploymentResponse>(
    API_ENDPOINTS.accountsCapitalDeployment,
  );
  return {
    data: data?.accounts ?? [],
    totalUsableCapital: data?.total_usable_capital ?? 0,
    avgReadinessScore: data?.avg_readiness_score ?? 0,
    isLoading,
    isError: !!error,
    error,
    mutate,
  };
}

export function useActiveTrades() {
  const { data, error, isLoading, mutate } = useApiQuery<
    ActiveTradesResponse | Trade[]
  >(
    API_ENDPOINTS.tradesActive,
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useAllVerdicts(options?: { refreshInterval?: number }) {
  const { data, error, isLoading, mutate } = useApiQuery<L12Verdict[] | Record<string, L12Verdict>>(
    API_ENDPOINTS.verdictAll,
    options?.refreshInterval ? { refetchInterval: options.refreshInterval } : undefined,
  );
  const normalized = normalizeVerdictResponse(data);
  return { data: normalized, isLoading, isError: !!error, error, mutate };
}

function normalizeVerdictResponse(
  data: L12Verdict[] | Record<string, L12Verdict> | undefined
): L12Verdict[] {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  // Handle { verdicts: L12Verdict[] | Record<string, L12Verdict> } envelope
  if ("verdicts" in data) {
    const inner = (data as Record<string, unknown>).verdicts;
    if (Array.isArray(inner)) return inner as L12Verdict[];
    if (inner && typeof inner === "object") return Object.values(inner as Record<string, L12Verdict>);
  }
  return Object.values(data);
}

export function useHealth() {
  const { data, error, isLoading } = useApiQuery<SystemHealth>(
    API_ENDPOINTS.health,
  );
  return { data, isLoading, isError: !!error, error };
}

export function useOrchestratorState() {
  const { data, error, isLoading, mutate } = useApiQuery<OrchestratorState>(
    API_ENDPOINTS.orchestratorState,
    { refetchInterval: 15_000 },
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useContext() {
  const { data, error, isLoading } = useApiQuery<ContextSnapshot>(
    API_ENDPOINTS.context,
    { refetchInterval: 30_000 },
  );
  return { data, isLoading, isError: !!error, error };
}

export function useExecution() {
  const { data, error, isLoading } = useApiQuery<ExecutionState>(
    API_ENDPOINTS.execution,
  );
  return { data, isLoading, isError: !!error, error };
}

export function useRiskSnapshot(accountId: string) {
  const { data, error, isLoading } = useApiQuery<RiskSnapshot>(
    accountId ? API_ENDPOINTS.riskSnapshotByAccount(accountId) : null,
  );
  return { data, isLoading, isError: !!error, error };
}

export function usePipeline(pair: string) {
  const { data, error, isLoading } = useApiQuery<PipelineData>(
    pair ? `/api/v1/pipeline/${pair}` : null,
  );
  return { data, error, isLoading };
}

export function useCalendarEvents(period = "today", impact?: string) {
  const params = new URLSearchParams();
  if (impact) params.set("impact", impact);
  const endpoint = period === "upcoming"
    ? `${API_ENDPOINTS.calendarUpcoming}?${params.toString()}`
    : `${API_ENDPOINTS.calendar}?${params.toString()}`;
  const { data, error, isLoading } = useApiQuery<CalendarDayResponse | CalendarUpcomingResponse | CalendarEvent[]>(
    endpoint,
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
  const { data, error, isLoading, mutate } = useApiQuery<CalendarBlockerResponse>(
    `${API_ENDPOINTS.calendarBlocker}${query}`,
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useCalendarSourceHealth() {
  const { data, error, isLoading, mutate } = useApiQuery<CalendarHealthResponse>(
    API_ENDPOINTS.calendarHealth,
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useEAStatus() {
  const { data, error, isLoading, mutate } = useApiQuery<EAStatus>(
    API_ENDPOINTS.eaStatus,
    { refetchInterval: 5000 },
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useEALogs(agentId?: string) {
  const url = agentId
    ? `${API_ENDPOINTS.eaLogs}?agent_id=${encodeURIComponent(agentId)}`
    : API_ENDPOINTS.eaLogs;
  const { data, error, isLoading, mutate } = useApiQuery<EALog[]>(url);
  return { data, isLoading, isError: !!error, error, mutate };
}

export function useEAAgents() {
  const { data, error, isLoading, mutate } = useApiQuery<EAAgent[]>(
    API_ENDPOINTS.eaAgents,
    { refetchInterval: 5000 },
  );
  return { data: data ?? [], isLoading, isError: !!error, error, mutate };
}

export function usePropFirmPhase(accountId: string) {
  const { data, error, isLoading } = useApiQuery<PropFirmPhase>(
    accountId ? API_ENDPOINTS.propFirmPhase(accountId) : null,
  );
  return { data, isLoading, isError: !!error, error };
}

export function usePropFirmStatus(accountId: string) {
  const { data, error, isLoading } = useApiQuery<PropFirmStatus>(
    accountId ? API_ENDPOINTS.propFirmStatus(accountId) : null,
  );
  return { data, isLoading, isError: !!error, error };
}

export function usePricesREST() {
  const { data, error, isLoading, mutate } = useApiQuery<PriceData[]>(
    "/api/v1/prices",
  );
  return { data, isLoading, isError: !!error, error, mutate };
}

export function usePairs() {
  const { data, error, isLoading } = useApiQuery<PairInfo[]>(
    "/api/v1/pairs",
  );
  return { data, isLoading, isError: !!error, error };
}

export function useProbabilitySummary() {
  const { data, error, isLoading } = useApiQuery<ProbabilitySummary>(
    "/api/v1/probability/summary",
  );
  return { data, isLoading, isError: !!error, error };
}

export function useProbabilityCalibration() {
  const { data, error, isLoading } = useApiQuery<ProbabilityCalibration>(
    "/api/v1/probability/calibration",
  );
  return { data, isLoading, isError: !!error, error };
}

export function useJournalToday() {
  const { data, error, isLoading } = useApiQuery<DailyJournal>(
    "/api/v1/journal/today",
  );
  return { data, isLoading, isError: !!error, error };
}

export function useJournalWeekly() {
  const { data, error, isLoading } = useApiQuery<DailyJournal[]>(
    "/api/v1/journal/weekly",
  );
  return { data, isLoading, isError: !!error, error };
}

export function useJournalMetrics() {
  const { data, error, isLoading } = useApiQuery<JournalMetrics>(
    "/api/v1/journal/metrics",
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
  const { data, error, isLoading, mutate } = useApiQuery<AccountRiskSnapshot[]>(
    API_ENDPOINTS.accountsRiskSnapshot,
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

export async function createAccount(data: AccountCreate & { data_source?: string }): Promise<Account> {
  const body: CreateAccountRequest = {
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
    data_source: data.data_source || "MANUAL",
    prop_firm: Boolean(data.prop_firm_code),
    max_daily_dd_percent: 4,
    max_total_dd_percent: 8,
    max_concurrent_trades: 1,
    reason: "ACCOUNT_CREATE_FROM_UI",
  };
  return apiMutate(API_ENDPOINTS.accounts, body);
}

export async function restartEA(): Promise<void> {
  await apiMutate(API_ENDPOINTS.eaRestart, { reason: "MANUAL_RESTART" });
}

export async function setEASafeMode(enabled: boolean, reason: string): Promise<void> {
  await apiMutate(API_ENDPOINTS.eaSafeMode, { enabled, reason });
}
