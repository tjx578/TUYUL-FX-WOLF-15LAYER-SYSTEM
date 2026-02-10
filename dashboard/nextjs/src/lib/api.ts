/**
 * API client with SWR hooks for data fetching
 */

import useSWR from 'swr';
import type { L12Verdict, SystemHealth, ContextSnapshot, ExecutionState, PairInfo } from '@/types';

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

/**
 * Hook: Fetch L12 verdict for a pair
 */
export function useVerdict(pair: string) {
  const { data, error, isLoading } = useSWR<L12Verdict>(
    pair ? `${API_BASE}/api/v1/l12/${pair}` : null,
    fetcher,
    {
      refreshInterval: VERDICT_REFRESH,
      revalidateOnFocus: true,
    }
  );

  return {
    verdict: data,
    isLoading,
    isError: error,
  };
}

/**
 * Hook: Fetch all verdicts
 */
export function useAllVerdicts() {
  const { data, error, isLoading } = useSWR<Record<string, L12Verdict>>(
    `${API_BASE}/api/v1/verdict/all`,
    fetcher,
    {
      refreshInterval: VERDICT_REFRESH,
    }
  );

  return {
    verdicts: data,
    isLoading,
    isError: error,
  };
}

/**
 * Hook: Fetch system health
 */
export function useHealth() {
  const { data, error, isLoading } = useSWR<SystemHealth>(
    `${API_BASE}/health`,
    fetcher,
    {
      refreshInterval: HEALTH_REFRESH,
    }
  );

  return {
    health: data,
    isLoading,
    isError: error,
  };
}

/**
 * Hook: Fetch live context snapshot
 */
export function useContext() {
  const { data, error, isLoading } = useSWR<ContextSnapshot>(
    `${API_BASE}/api/v1/context`,
    fetcher,
    {
      refreshInterval: CONTEXT_REFRESH,
    }
  );

  return {
    context: data,
    isLoading,
    isError: error,
  };
}

/**
 * Hook: Fetch execution state
 */
export function useExecution() {
  const { data, error, isLoading } = useSWR<ExecutionState>(
    `${API_BASE}/api/v1/execution`,
    fetcher,
    {
      refreshInterval: VERDICT_REFRESH,
    }
  );

  return {
    execution: data,
    isLoading,
    isError: error,
  };
}

/**
 * Hook: Fetch available pairs
 */
export function usePairs() {
  const { data, error, isLoading } = useSWR<PairInfo[]>(
    `${API_BASE}/api/v1/pairs`,
    fetcher,
    {
      // Pairs list doesn't change often
      refreshInterval: 60000,
      revalidateOnFocus: false,
    }
  );

  return {
    pairs: data,
    isLoading,
    isError: error,
  };
}
