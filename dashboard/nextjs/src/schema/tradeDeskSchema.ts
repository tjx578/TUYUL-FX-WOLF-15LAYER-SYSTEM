/**
 * @deprecated Import from `@/features/trades/model/tradeDeskSchema` instead.
 * This re-export exists for backward-compat during trades domain cutover (PR-005).
 */
export {
  AnomalySchema,
  TradeAnomalySchema,
  TimelineEventSchema,
  PairExposureSchema,
  AccountExposureSchema,
  ExposureSummarySchema,
  TRADE_STATUSES,
  TERMINAL_STATUSES,
  TradeDeskTradeSchema,
  TradeDeskCountsSchema,
  TradeDeskResponseSchema,
  TradeDetailResponseSchema,
} from "@/features/trades/model/tradeDeskSchema";

export type {
  Anomaly,
  TradeAnomaly,
  TimelineEvent,
  PairExposure,
  AccountExposure,
  ExposureSummary,
  TradeDeskTrade,
  TradeDeskCounts,
  TradeDeskResponse,
  TradeDetailResponse,
  TradeStatus,
} from "@/features/trades/model/tradeDeskSchema";
