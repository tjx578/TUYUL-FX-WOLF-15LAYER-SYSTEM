import useSWR from "swr"
import type { Account } from "@/types/account"

const fetcher = async (url: string) => {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}${url}`,
    {
      credentials: "include"
    }
  )
import useSWR from "swr";
import type {
  L12Verdict,
  Trade,
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
import type { Account } from "@/types/account";

  if (!res.ok) {
    throw new Error("Failed to fetch data")
  }

  return res.json()
}

export function useAccounts() {
  const { data, error, isLoading } = useSWR<Account[]>(
    "/api/v1/accounts",
    fetcher
  )

  return {
    data,
    isLoading,
    isError: !!error
  }
}

