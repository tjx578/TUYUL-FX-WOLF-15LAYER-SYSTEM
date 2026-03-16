import { z } from "zod";

// ── Anomaly ──────────────────────────────────────────────────

export const AnomalySchema = z.object({
  type: z.string(),
  message: z.string(),
  severity: z.enum(["WARNING", "CRITICAL", "INFO"]),
});

export const TradeAnomalySchema = z.object({
  trade_id: z.string(),
  anomalies: z.array(AnomalySchema),
});

// ── Execution Timeline ───────────────────────────────────────

export const TimelineEventSchema = z.object({
  event: z.string(),
  status: z.string(),
  timestamp: z.string().or(z.number()),
  close_reason: z.string().optional(),
  pnl: z.number().optional(),
});

// ── Exposure ─────────────────────────────────────────────────

export const PairExposureSchema = z.object({
  pair: z.string(),
  total_lots: z.number(),
  buy_lots: z.number(),
  sell_lots: z.number(),
  count: z.number(),
});

export const AccountExposureSchema = z.object({
  account_id: z.string(),
  total_lots: z.number(),
  count: z.number(),
  pairs: z.array(z.string()),
});

export const ExposureSummarySchema = z.object({
  by_pair: z.array(PairExposureSchema),
  by_account: z.array(AccountExposureSchema),
  total_lots: z.number(),
  total_trades: z.number(),
});

// ── Trade Status Enum ─────────────────────────────────────────

export const TRADE_STATUSES = [
  "INTENDED", "PENDING", "OPEN", "CLOSED",
  "CANCELLED", "SKIPPED", "PARTIALLY_FILLED", "REJECTED",
] as const;

export type TradeStatus = (typeof TRADE_STATUSES)[number];

export const TERMINAL_STATUSES: readonly TradeStatus[] = [
  "CLOSED", "CANCELLED", "SKIPPED", "REJECTED",
] as const;

// ── Extended Trade Schema ────────────────────────────────────

/**
 * Raw schema accepts both backend field aliases (symbol/pair, side/direction, lot/lot_size).
 * The transform normalises into canonical names so consumers don't need fallback chains.
 */
const TradeDeskTradeRaw = z.object({
  trade_id: z.string().min(1),
  signal_id: z.string().optional(),
  account_id: z.string().min(1),
  symbol: z.string().optional(),
  pair: z.string().optional(),
  side: z.enum(["BUY", "SELL"]).optional(),
  direction: z.string().optional(),
  lot: z.number().optional(),
  lot_size: z.number().optional(),
  status: z.enum(TRADE_STATUSES).or(z.string().min(1)),
  entry_price: z.number().optional(),
  stop_loss: z.number().optional(),
  take_profit: z.number().optional(),
  pnl: z.number().optional(),
  opened_at: z.string().optional(),
  closed_at: z.string().optional(),
  created_at: z.string().optional(),
  confirmed_at: z.string().optional(),
  close_reason: z.string().optional(),
  current_price: z.number().optional(),
  total_risk_percent: z.number().optional(),
  total_risk_amount: z.number().optional(),
});

export const TradeDeskTradeSchema = TradeDeskTradeRaw.transform((t) => ({
  trade_id: t.trade_id,
  signal_id: t.signal_id,
  account_id: t.account_id,
  pair: t.pair ?? t.symbol,
  direction: (t.direction ?? t.side) as "BUY" | "SELL" | undefined,
  lot_size: t.lot_size ?? t.lot,
  status: t.status,
  entry_price: t.entry_price,
  stop_loss: t.stop_loss,
  take_profit: t.take_profit,
  pnl: t.pnl,
  opened_at: t.opened_at,
  closed_at: t.closed_at,
  created_at: t.created_at,
  confirmed_at: t.confirmed_at,
  close_reason: t.close_reason,
  current_price: t.current_price,
  total_risk_percent: t.total_risk_percent,
  total_risk_amount: t.total_risk_amount,
}));

// ── Desk Response ────────────────────────────────────────────

export const TradeDeskCountsSchema = z.object({
  pending: z.number(),
  open: z.number(),
  closed: z.number(),
  cancelled: z.number(),
  total: z.number(),
});

export const TradeDeskResponseSchema = z.object({
  trades: z.object({
    pending: z.array(TradeDeskTradeSchema),
    open: z.array(TradeDeskTradeSchema),
    closed: z.array(TradeDeskTradeSchema),
    cancelled: z.array(TradeDeskTradeSchema),
  }),
  exposure: ExposureSummarySchema,
  anomalies: z.array(TradeAnomalySchema),
  counts: TradeDeskCountsSchema,
  server_ts: z.number(),
});

// ── Trade Detail Response ────────────────────────────────────

export const TradeDetailResponseSchema = z.object({
  trade: TradeDeskTradeSchema,
  timeline: z.array(TimelineEventSchema),
  anomalies: z.array(AnomalySchema),
});

// ── Type Exports ─────────────────────────────────────────────

export type Anomaly = z.infer<typeof AnomalySchema>;
export type TradeAnomaly = z.infer<typeof TradeAnomalySchema>;
export type TimelineEvent = z.infer<typeof TimelineEventSchema>;
export type PairExposure = z.infer<typeof PairExposureSchema>;
export type AccountExposure = z.infer<typeof AccountExposureSchema>;
export type ExposureSummary = z.infer<typeof ExposureSummarySchema>;
export type TradeDeskTrade = z.infer<typeof TradeDeskTradeSchema>;
export type TradeDeskCounts = z.infer<typeof TradeDeskCountsSchema>;
export type TradeDeskResponse = z.infer<typeof TradeDeskResponseSchema>;
export type TradeDetailResponse = z.infer<typeof TradeDetailResponseSchema>;
