/**
 * API client with SWR hooks for data fetching.
 *
 * Real-time data (prices, trades, candles, risk) now uses WebSocket hooks
 * in lib/websocket.ts.  SWR is retained for request/response endpoints
 * (verdicts, journal, accounts, REST trade operations).
 */

import useSWR from 'swr';
import type {
  L12Verdict,
  SystemHealth,
  ContextSnapshot,
  ExecutionState,
  PairInfo,
  Trade,
  DailyJournal,
  JournalMetrics,
  Account,
  RiskSnapshot,
} from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Refresh intervals from env
const VERDICT_REFRESH = Number(process.env.NEXT_PUBLIC_VERDICT_REFRESH_MS) || 5000;
const CONTEXT_REFRESH = Number(process.env.NEXT_PUBLIC_CONTEXT_REFRESH_MS) || 10000;
const HEALTH_REFRESH = Number(process.env.NEXT_PUBLIC_HEALTH_REFRESH_MS) || 30000;

/**
 * Generic fetcher for SWR
 */
const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
};

// ---------------------------------------------------------------------------
// Verdict / Core hooks
// ---------------------------------------------------------------------------

export function useVerdict(pair: string) {
  const { data, error, isLoading } = useSWR<L12Verdict>(
    pair ? `${API_BASE}/api/v1/l12/${pair}` : null,
    fetcher,
    { refreshInterval: VERDICT_REFRESH, revalidateOnFocus: true }
  );
  return { verdict: data, isLoading, isError: error };
}

export function useAllVerdicts() {
  const { data, error, isLoading } = useSWR<Record<string, L12Verdict>>(
    `${API_BASE}/api/v1/verdict/all`,
    fetcher,
    { refreshInterval: VERDICT_REFRESH }
  );
  return { verdicts: data, isLoading, isError: error };
}

export function useHealth() {
  const { data, error, isLoading } = useSWR<SystemHealth>(
    `${API_BASE}/health`,
    fetcher,
    { refreshInterval: HEALTH_REFRESH }
  );
  return { health: data, isLoading, isError: error };
}

export function useContext() {
  const { data, error, isLoading } = useSWR<ContextSnapshot>(
    `${API_BASE}/api/v1/context`,
    fetcher,
    { refreshInterval: CONTEXT_REFRESH }
  );
  return { context: data, isLoading, isError: error };
}

export function useExecution() {
  const { data, error, isLoading } = useSWR<ExecutionState>(
    `${API_BASE}/api/v1/execution`,
    fetcher,
    { refreshInterval: VERDICT_REFRESH }
  );
  return { execution: data, isLoading, isError: error };
}

export function usePairs() {
  const { data, error, isLoading } = useSWR<PairInfo[]>(
    `${API_BASE}/api/v1/pairs`,
    fetcher,
    { refreshInterval: 60000, revalidateOnFocus: false }
  );
  return { pairs: data, isLoading, isError: error };
}

// ---------------------------------------------------------------------------
// Trade management (REST)
// ---------------------------------------------------------------------------

export function useActiveTrades() {
  const { data, error, isLoading, mutate } = useSWR<Trade[]>(
    `${API_BASE}/api/v1/trades/active`,
    fetcher,
    { refreshInterval: 3000 }
  );
  return { trades: data || [], isLoading, isError: error, mutate };
}

export function useTrade(tradeId: string | null) {
  const { data, error, isLoading } = useSWR<Trade>(
    tradeId ? `${API_BASE}/api/v1/trades/${tradeId}` : null,
    fetcher,
    { refreshInterval: 2000 }
  );
  return { trade: data, isLoading, isError: error };
}

/** Take a trade signal */
export async function takeSignal(signalId: string, accountId: string): Promise<Trade> {
  const res = await fetch(`${API_BASE}/api/v1/trades/take`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ signal_id: signalId, account_id: accountId }),
  });
  if (!res.ok) throw new Error(`Take signal failed: ${res.status}`);
  return res.json();
}

/** Skip a trade signal */
export async function skipSignal(signalId: string, reason?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/trades/skip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ signal_id: signalId, reason }),
  });
  if (!res.ok) throw new Error(`Skip signal failed: ${res.status}`);
}

/** Confirm a pending order */
export async function confirmTrade(tradeId: string): Promise<Trade> {
  const res = await fetch(`${API_BASE}/api/v1/trades/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ trade_id: tradeId }),
  });
  if (!res.ok) throw new Error(`Confirm trade failed: ${res.status}`);
  return res.json();
}

/** Close a trade manually */
export async function closeTrade(tradeId: string, reason?: string): Promise<Trade> {
  const res = await fetch(`${API_BASE}/api/v1/trades/close`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ trade_id: tradeId, reason }),
  });
  if (!res.ok) throw new Error(`Close trade failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Journal (REST)
// ---------------------------------------------------------------------------

export function useJournalToday() {
  const { data, error, isLoading } = useSWR<DailyJournal>(
    `${API_BASE}/api/v1/journal/today`,
    fetcher,
    { refreshInterval: 10000 }
  );
  return { journal: data, isLoading, isError: error };
}

export function useJournalWeekly() {
  const { data, error, isLoading } = useSWR<DailyJournal[]>(
    `${API_BASE}/api/v1/journal/weekly`,
    fetcher,
    { refreshInterval: 30000 }
  );
  return { journals: data || [], isLoading, isError: error };
}

export function useJournalMetrics() {
  const { data, error, isLoading } = useSWR<JournalMetrics>(
    `${API_BASE}/api/v1/journal/metrics`,
    fetcher,
    { refreshInterval: 15000 }
  );
  return { metrics: data, isLoading, isError: error };
}

// ---------------------------------------------------------------------------
// Accounts (REST)
// ---------------------------------------------------------------------------

export function useAccounts() {
  const { data, error, isLoading, mutate } = useSWR<Account[]>(
    `${API_BASE}/api/v1/accounts`,
    fetcher,
    { refreshInterval: 30000 }
  );
  return { accounts: data || [], isLoading, isError: error, mutate };
}

export function useAccount(accountId: string | null) {
  const { data, error, isLoading } = useSWR<Account>(
    accountId ? `${API_BASE}/api/v1/accounts/${accountId}` : null,
    fetcher,
    { refreshInterval: 10000 }
  );
  return { account: data, isLoading, isError: error };
}

// ---------------------------------------------------------------------------
// Risk (REST — complementary to WS /ws/risk)
// ---------------------------------------------------------------------------

export function useRiskSnapshot(accountId: string | null) {
  const { data, error, isLoading } = useSWR<RiskSnapshot>(
    accountId ? `${API_BASE}/api/v1/risk/${accountId}/snapshot` : null,
    fetcher,
    { refreshInterval: 5000 }
  );
  return { snapshot: data, isLoading, isError: error };
}

// ---------------------------------------------------------------------------
// Prices (REST fallback — prefer WS for real-time)
// ---------------------------------------------------------------------------

export function usePricesREST() {
  const { data, error, isLoading } = useSWR<Record<string, any>>(
    `${API_BASE}/api/v1/prices`,
    fetcher,
    { refreshInterval: 2000 }
  );
  return { prices: data || {}, isLoading, isError: error };
}
