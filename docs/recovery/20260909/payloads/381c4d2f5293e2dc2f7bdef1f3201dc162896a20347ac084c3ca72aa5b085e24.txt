import { z } from "zod";
import { ExecutionStateUpdatedSchema } from "./executionSchema";
import {
  PipelineResultSchema,
  VerdictUpdatedPayloadSchema,
  VerdictSnapshotPayloadSchema,
  PipelineUpdatedPayloadSchema,
} from "./pipelineResultSchema";
import { PreferencesSchema } from "./preferencesSchema";

const RiskStateSchema = z.object({
  account_id: z.string().min(1),
  dd_pct: z.number(),
});

// All valid mode strings from backend SystemStatusView + DegradationMode in useSystemStore.
// Must stay in sync with wsEvents.ts SystemStatusView and useSystemStore DegradationMode.
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

export const PreferencesUpdatedEventSchema = z.object({
  type: z.literal("PreferencesUpdated"),
  payload: PreferencesSchema,
});

// Domain-specific WS endpoint events (prices, risk)
export const PriceUpdatedEventSchema = z.object({
  type: z.literal("PriceUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

export const PricesSnapshotEventSchema = z.object({
  type: z.literal("PricesSnapshot"),
  payload: z.record(z.string(), z.unknown()),
});

export const RiskUpdatedEventSchema = z.object({
  type: z.literal("RiskUpdated"),
  payload: z.record(z.string(), z.unknown()),
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
  payload: z.record(z.string(), z.unknown()),
});

export const CandleFormingEventSchema = z.object({
  type: z.literal("CandleForming"),
  payload: z.record(z.string(), z.unknown()),
});

export const EquityUpdatedEventSchema = z.object({
  type: z.literal("EquityUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

export const AlertCreatedEventSchema = z.object({
  type: z.literal("AlertCreated"),
  payload: z.record(z.string(), z.unknown()),
});

export const AlertUpdatedEventSchema = z.object({
  type: z.literal("AlertUpdated"),
  payload: z.record(z.string(), z.unknown()),
});

// ── Live feed heartbeat events from /ws/live ──
// Payload: { signals, accounts, trades } — used for initial snapshot on connection.
export const LiveSnapshotEventSchema = z.object({
  type: z.literal("LiveSnapshot"),
  payload: z.record(z.string(), z.unknown()),
});

// Payload: { signal_count, account_count, active_trade_count, server_ts, engine_status }
export const LiveHeartbeatStateEventSchema = z.object({
  type: z.literal("LiveHeartbeatState"),
  payload: z.record(z.string(), z.unknown()),
});

// pipeline.snapshot: { pair, pipelines: Record<symbol, pipelineData> }
export const PipelineSnapshotEventSchema = z.object({
  type: z.literal("PipelineSnapshot"),
  payload: z.record(z.string(), z.unknown()),
});

export const WsEventSchema = z.discriminatedUnion("type", [
  // Legacy / frontend-native
  PipelineResultUpdatedEventSchema,
  ExecutionStateUpdatedEventSchema,
  RiskStateUpdatedEventSchema,
  SystemStatusUpdatedEventSchema,
  PreferencesUpdatedEventSchema,
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
  // Live feed heartbeat events
  LiveSnapshotEventSchema,
  LiveHeartbeatStateEventSchema,
  PipelineSnapshotEventSchema,
]);

export type WsEvent = z.infer<typeof WsEventSchema>;
export type WsEventParsed = z.infer<typeof WsEventSchema>;
