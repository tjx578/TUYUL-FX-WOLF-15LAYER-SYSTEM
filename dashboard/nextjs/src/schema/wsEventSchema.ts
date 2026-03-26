import { z } from "zod";
import { CircuitBreakerState, RiskSeverity } from "@/types";
import { ExecutionStateUpdatedSchema } from "./executionSchema";
import {
  PipelineResultSchema,
  VerdictUpdatedPayloadSchema,
  VerdictSnapshotPayloadSchema,
  PipelineUpdatedPayloadSchema,
} from "./pipelineResultSchema";

const RiskStateSchema = z.object({
  account_id: z.string().min(1),
  dd_pct: z.number(),
});

const SystemStatusSchema = z.object({
  mode: z.union([
    z.literal("NORMAL"),
    z.literal("SSE"),
    z.literal("POLLING"),
    z.literal("DEGRADED"),
    z.literal("RECONNECTING_WS"),
    z.literal("POLLING_REST"),
    z.literal("STALE"),
    z.literal("STALE_PRESERVED"),
    z.literal("NO_PRODUCER"),
    z.literal("NO_TRANSPORT"),
    z.literal("DEGRADED_BUT_REFRESHING"),
  ]),
  reason: z.string().optional(),
  updated_at: z.string().optional(),
});

const PriceDataSchema = z.object({
  symbol: z.string().min(1),
  bid: z.number(),
  ask: z.number(),
  spread: z.number(),
  timestamp: z.number(),
  change_24h: z.number().optional(),
  change_percent_24h: z.number().optional(),
});

const RiskUpdatedSchema = z
  .object({
    can_trade: z.boolean(),
    block_reason: z.string(),
    account_id: z.string().min(1),
    daily_dd_percent: z.number(),
    daily_dd_limit: z.number(),
    total_dd_percent: z.number(),
    total_dd_limit: z.number(),
    open_risk_percent: z.number(),
    open_trades: z.number(),
    circuit_breaker: z.nativeEnum(CircuitBreakerState),
    severity: z.nativeEnum(RiskSeverity),
    timestamp: z.number(),
  })
  .passthrough();

const CandleDataSchema = z.object({
  symbol: z.string().min(1),
  timeframe: z.string().min(1),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().optional(),
  timestamp: z.number(),
});

const CandleSnapshotPayloadSchema = z
  .object({
    symbol: z.string().min(1),
    candles: z.array(CandleDataSchema),
  })
  .passthrough();

const EquityUpdatedPayloadSchema = z
  .object({
    timestamp: z.number(),
    equity: z.number(),
    balance: z.number(),
    daily_dd: z.number(),
    total_dd: z.number(),
    account_id: z.string().optional(),
  })
  .passthrough();

const AlertPayloadSchema = z
  .object({
    alert_id: z.string().min(1),
    type: z.enum([
      "ORDER_PLACED",
      "ORDER_FILLED",
      "ORDER_CANCELLED",
      "SYSTEM_VIOLATION",
      "RISK_LIMIT_REACHED",
      "PROP_FIRM_BREACH",
      "CIRCUIT_BREAKER_OPEN",
      "NEWS_LOCK",
      "SESSION_CHANGE",
    ]),
    severity: z.enum(["INFO", "WARNING", "CRITICAL"]),
    message: z.string().min(1),
    timestamp: z.string().min(1),
    pair: z.string().optional(),
    trade_id: z.string().optional(),
  })
  .passthrough();

// ── Legacy / frontend-native event types ──

export const PipelineResultUpdatedEventSchema = z.object({
  type: z.literal("PipelineResultUpdated"),
  payload: PipelineResultSchema,
});

export const ExecutionStateUpdatedEventSchema = z.object({
  type: z.literal("ExecutionStateUpdated"),
  payload: ExecutionStateUpdatedSchema,
});

export const RiskStateUpdatedEventSchema = z.object({
  type: z.literal("RiskStateUpdated"),
  payload: RiskStateSchema,
});

export const SystemStatusUpdatedEventSchema = z.object({
  type: z.literal("SystemStatusUpdated"),
  payload: SystemStatusSchema,
});



// Domain-specific WS endpoint events (prices, risk)
export const PriceUpdatedEventSchema = z.object({
  type: z.literal("PriceUpdated"),
  payload: z.record(z.string(), PriceDataSchema),
});

export const PricesSnapshotEventSchema = z.object({
  type: z.literal("PricesSnapshot"),
  payload: z.record(z.string(), PriceDataSchema),
});

export const RiskUpdatedEventSchema = z.object({
  type: z.literal("RiskUpdated"),
  payload: RiskUpdatedSchema,
});

// ── Backend-native event types (normalised by realtimeClient) ──

export const VerdictUpdatedEventSchema = z.object({
  type: z.literal("VerdictUpdated"),
  payload: VerdictUpdatedPayloadSchema,
});

export const VerdictSnapshotEventSchema = z.object({
  type: z.literal("VerdictSnapshot"),
  payload: VerdictSnapshotPayloadSchema,
});

export const PipelineUpdatedEventSchema = z.object({
  type: z.literal("PipelineUpdated"),
  payload: PipelineUpdatedPayloadSchema,
});

// ── Domain event types (mapped from backend by realtimeClient) ──

export const SignalUpdatedEventSchema = z.object({
  type: z.literal("SignalUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

export const TradeSnapshotEventSchema = z.object({
  type: z.literal("TradeSnapshot"),
  payload: z.record(z.string(), z.unknown()),
});

export const TradeUpdatedEventSchema = z.object({
  type: z.literal("TradeUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

export const CandleSnapshotEventSchema = z.object({
  type: z.literal("CandleSnapshot"),
  payload: CandleSnapshotPayloadSchema,
});

export const CandleFormingEventSchema = z.object({
  type: z.literal("CandleForming"),
  payload: CandleDataSchema,
});

export const EquityUpdatedEventSchema = z.object({
  type: z.literal("EquityUpdated"),
  payload: EquityUpdatedPayloadSchema,
});

export const AlertCreatedEventSchema = z.object({
  type: z.literal("AlertCreated"),
  payload: AlertPayloadSchema,
});

export const AlertUpdatedEventSchema = z.object({
  type: z.literal("AlertUpdated"),
  payload: AlertPayloadSchema,
});

export const WsEventSchema = z.discriminatedUnion("type", [
  // Legacy / frontend-native
  PipelineResultUpdatedEventSchema,
  ExecutionStateUpdatedEventSchema,
  RiskStateUpdatedEventSchema,
  SystemStatusUpdatedEventSchema,
  PriceUpdatedEventSchema,
  PricesSnapshotEventSchema,
  RiskUpdatedEventSchema,
  // Backend-native (normalised by realtimeClient)
  VerdictUpdatedEventSchema,
  VerdictSnapshotEventSchema,
  PipelineUpdatedEventSchema,
  // Domain events (mapped from backend)
  SignalUpdatedEventSchema,
  TradeSnapshotEventSchema,
  TradeUpdatedEventSchema,
  CandleSnapshotEventSchema,
  CandleFormingEventSchema,
  EquityUpdatedEventSchema,
  AlertCreatedEventSchema,
  AlertUpdatedEventSchema,
]);

export type WsEvent = z.infer<typeof WsEventSchema>;
export type WsEventParsed = z.infer<typeof WsEventSchema>;
