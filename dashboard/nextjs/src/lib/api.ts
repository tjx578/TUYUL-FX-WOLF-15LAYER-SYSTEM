/**
 * Re-export barrel for backward compatibility.
 *
 * New code should import directly from domain modules:
 *   @/shared/api/client                    — fetcher, apiMutate, useApiQuery, POLL_INTERVALS, API_ENDPOINTS
 *   @/features/accounts/api/accounts.api   — useAccounts, createAccount, archiveAccount, …
 *   @/features/signals/api/verdicts.api    — useAllVerdicts, takeSignal, skipSignal, …
 *   @/features/trades/api/tradesQuery.api  — useActiveTrades, confirmTrade, closeTrade, …
 *   @/features/journal/api/journal.api     — useJournalToday, useJournalWeekly, useJournalMetrics
 *   @/features/news/api/calendar.api       — useCalendarEvents, useCalendarBlocker, …
 *   @/features/risk/api/risk.api           — useRiskSnapshot
 *   @/shared/api/system.api                — useHealth, useContext, useExecution, …
 *   @/shared/api/market.api                — usePricesREST, usePairs, …
 *   @/shared/api/propfirm.api              — usePropFirmPhase, fetchPropFirms, …
 *   @/shared/api/ea.api                    — deprecated EA shims
 */

// ── Shared client primitives ──
export { POLL_INTERVALS, API_ENDPOINTS } from "@/shared/api/client";

// ── Accounts ──
export {
  useAccounts,
  useCapitalDeployment,
  useAccountsRiskSnapshot,
  createAccount,
  archiveAccount,
  type AccountRiskSnapshot,
} from "@/features/accounts/api/accounts.api";

// ── Signals / Verdicts ──
export {
  useAllVerdicts,
  takeSignal,
  skipSignal,
  previewRiskMulti,
  type TakeSignalRequest,
  type RiskPreviewMultiRequest,
  type RiskPreviewAccountItem,
  type SkipSignalRequest,
} from "@/features/signals/api/verdicts.api";

// ── Trades ──
export {
  useActiveTrades,
  confirmTrade,
  closeTrade,
  type ActiveTradesResponse,
} from "@/features/trades/api/tradesQuery.api";

// ── Journal ──
export {
  useJournalToday,
  useJournalWeekly,
  useJournalMetrics,
} from "@/features/journal/api/journal.api";

// ── Calendar / News ──
export {
  useCalendarEvents,
  useCalendarBlocker,
  useCalendarSourceHealth,
} from "@/features/news/api/calendar.api";

// ── Risk ──
export { useRiskSnapshot } from "@/features/risk/api/risk.api";

// ── System ──
export {
  useHealth,
  useOrchestratorState,
  useContext,
  useExecution,
  usePipeline,
} from "@/shared/api/system.api";

// ── Market Data ──
export {
  usePricesREST,
  usePairs,
  useProbabilitySummary,
  useProbabilityCalibration,
} from "@/shared/api/market.api";

// ── Prop Firm ──
export {
  usePropFirmPhase,
  usePropFirmStatus,
  fetchPropFirms,
  fetchPropFirmPrograms,
  fetchPropFirmRules,
} from "@/shared/api/propfirm.api";

// ── EA (deprecated — sunset 2026-06-01) ──
export {
  useEAStatus,
  useEALogs,
  useEAAgents,
  eaPing,
  useEAPing,
  restartEA,
  setEASafeMode,
} from "@/shared/api/ea.api";

